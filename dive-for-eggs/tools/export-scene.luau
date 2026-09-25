-- Exports the built world (real builder modules, mock API) as JSON for the offline
-- preview renderer, together with the nine review camera views.
--   lune run tools/export-scene.luau [output.json]

local fs = require("@lune/fs")
local process = require("@lune/process")
local serde = require("@lune/serde")

local Loader = require("./mock/loader")
local Scene = require("./mock/scene")

local ROOT = string.gsub((string.gsub(process.cwd, "/$", "")), "/tools$", "")
if not fs.isDir(ROOT .. "/src") then
	ROOT = string.gsub(process.cwd, "/$", "") .. "/dive-for-eggs"
end
local output = process.args[1] or (ROOT .. "/tools/preview/scene.json")

local world, Config = Loader.buildWorld(ROOT .. "/src")
local H, S = Config.Hub, Config.Seabed

local function round(v: number): number
	return math.floor(v * 1000 + 0.5) / 1000
end

local function hex(c): string
	return c:ToHex()
end

-- Stall a part belongs to (for the isolated turnaround), or "".
local function stallTag(part): string
	local node = part.Parent
	while node do
		if node.Parent and node.Parent.Name == "CentralStalls" then
			return node.Name
		end
		node = node.Parent
	end
	return ""
end

-- Part records: position, rotation (row-major), size, colour, transparency, kind, studs, tag.
-- kind: 0 solid, 1 neon glow, 2 ellipsoid shell, 3 water/glass.
local parts = {}
for _, part in Scene.parts(world) do
	if part.Transparency < 1 then
		local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = part.CFrame:GetComponents()
		local kind = 0
		if part:FindFirstChildOfClass("SpecialMesh") then
			kind = 2
		elseif part.Material.Name == "Neon" then
			kind = 1
		elseif part.Material.Name == "Glass" or part.Transparency > 0 then
			kind = 3
		end
		local studs = 0
		if part.TopSurface.Name == "Studs" then
			studs = if part.FrontSurface.Name == "Studs" then 2 else 1
		end
		local s = part.Size
		table.insert(parts, {
			round(x), round(y), round(z),
			round(r00), round(r01), round(r02),
			round(r10), round(r11), round(r12),
			round(r20), round(r21), round(r22),
			round(s.X), round(s.Y), round(s.Z),
			hex(part.Color),
			round(part.Transparency),
			kind,
			studs,
			stallTag(part),
		})
	end
end

local lights = {}
for _, d in world:GetDescendants() do
	if d.ClassName == "PointLight" then
		local p = d.Parent.Position
		table.insert(lights, { round(p.X), round(p.Y), round(p.Z), hex(d.Color), d.Range })
	end
end

local depthLighting = {}
for _, frame in Config.DepthLighting do
	local out = {}
	for key, value in frame do
		out[key] = if type(value) == "number" then value else hex(value)
	end
	table.insert(depthLighting, out)
end

------------------------------------------------------------------------ camera views
local heightAt = Scene.heightRaster(world.Seabed, S.CELL, S.FINE_HALF_EXTENT)
local platform = H.PLATFORM_RADIUS

local function polar(angle: number, radius: number, y: number): { number }
	local a = math.rad(angle)
	return { round(math.sin(a) * radius), round(y), round(-math.cos(a) * radius) }
end
local function groundAt(angle: number, radius: number): number
	local p = polar(angle, radius, 0)
	return heightAt(p[1], p[3]) or S.SEABED_Y
end
local function yawFacing(from: { number }, to: { number }): number
	return math.atan2(to[1] - from[1], to[3] - from[3])
end

-- First big drop along a direction = the great cliff lip.
local function findLip(angle: number): (number, number)
	local previous = groundAt(angle, platform + 150)
	for d = 152, 330, 2 do
		local y = groundAt(angle, platform + d)
		if previous - y > 30 then
			return platform + d - 2, previous
		end
		previous = y
	end
	error("no lip found at angle " .. angle)
end

local plots = {}
for _, plot in world.Hub.Plots:GetChildren() do
	local anchor = plot.AquariumPad.AquariumAnchor
	table.insert(plots, {
		id = plot:GetAttribute("PlotId"),
		position = { round(anchor.Position.X), round(anchor.Position.Y), round(anchor.Position.Z) },
	})
end
local gates = {}
for i, angle in H.GATE_ANGLES do
	table.insert(gates, { name = H.GATE_NAMES[i], position = polar(angle, 152, 12) })
end

local stallFrames = {}
for _, stall in world.Hub.CentralStalls:GetChildren() do
	local components = { stall:GetPivot():GetComponents() }
	for i, v in components do
		components[i] = round(v)
	end
	stallFrames[stall.Name] = components
end
local StallBuilder = Loader.require(Loader.roblox.game:GetService("ServerScriptService").DiveWorldBuild.StallBuilder)
local statueZone = {
	radius = StallBuilder.statueRadius(Config),
	height = Config.Statue.TARGET_HEIGHT,
}

local spawn = world.Hub.HubSpawn
local spawnPos = { spawn.Position.X, H.FLOOR_Y, spawn.Position.Z }

local plotAngle = H.PLOT_FIRST_ANGLE
local shallowAngle, midAngle, cliffAngle, farAngle = 202, 214, 178, 248
local lipRadius, lipY = findLip(cliffAngle)
local midAvatarR = platform + 112

local views = {
	{
		id = "01-top-down",
		title = "1. Perfect top-down",
		caption = "Six plots (numbered), four gates, four stalls around the statue zone. Fog off for the layout check.",
		ortho = true,
		halfSize = 158,
		position = { 0, 700, 0 },
		target = { 0, 0, 0 },
		up = { 0, 0, -1 },
		fogScale = 0,
		labels = true,
		width = 1400,
		height = 1400,
	},
	{
		id = "02-high-three-quarter",
		title = "2. High 3/4 view",
		caption = "Same framing as the concept image, from the front (south) gate side.",
		position = { 0, 190, 300 },
		target = { 0, -8, 6 },
		fov = 50,
	},
	{
		id = "03-spawn-view",
		title = "3. Player spawn view",
		caption = "Spawn on the south avenue, facing the central market and the north gate.",
		position = { spawnPos[1], 8.5, spawnPos[3] + 14 },
		target = { 0, 3.5, 30 },
		fov = 70,
		avatars = { { position = spawnPos, yaw = math.pi } },
	},
	(function()
		local avatar = polar(plotAngle - 6, H.PAD_INNER_RADIUS - 2.2, H.FLOOR_Y)
		local centre = polar(plotAngle, H.PAD_INNER_RADIUS + H.PAD_DEPTH / 2, 0)
		return {
			id = "04-plot-close-up",
			title = "4. Plot 1 close-up",
			caption = "48 x 32 stud foundation pad, cyan edge = future glass side facing the centre.",
			position = polar(plotAngle - 20, 30, 17),
			target = centre,
			fov = 60,
			avatars = { { position = avatar, yaw = yawFacing(avatar, centre) } },
		}
	end)(),
	{
		id = "05-outside-bubble",
		title = "5. Outside the bubble, looking back",
		caption = "From the water south-east of the hub: bubble, gates, coral ring around the base.",
		position = polar(142, 262, 34),
		target = { 0, 22, 0 },
		fov = 60,
	},
	(function()
		local avatar = polar(shallowAngle, platform + 26, S.SEABED_Y + 5)
		return {
			id = "06-shallow-terrain",
			title = "6. Shallow terrain",
			caption = "Level starter seabed next to the platform, then the gentle descent begins.",
			position = polar(shallowAngle - 3, platform + 2, 16),
			target = polar(shallowAngle, platform + 150, -40),
			fov = 65,
			avatars = { { position = avatar, yaw = yawFacing(avatar, polar(shallowAngle, platform + 200, 0)) } },
		}
	end)(),
	(function()
		local avatarGround = groundAt(midAngle, midAvatarR)
		local avatar = polar(midAngle, midAvatarR, avatarGround + 8)
		local cameraR = platform + 82
		return {
			id = "07-mid-slope",
			title = "7. Mid-slope",
			caption = "Broken shelves and rock formations, looking down toward the deeper water.",
			position = polar(midAngle - 2, cameraR, groundAt(midAngle - 2, cameraR) + 30),
			target = polar(midAngle, platform + 300, -120),
			fov = 65,
			avatars = { { position = avatar, yaw = yawFacing(avatar, polar(midAngle, platform + 300, 0)) } },
		}
	end)(),
	(function()
		local avatar = polar(cliffAngle - 5, lipRadius - 2, lipY + 3)
		return {
			id = "08-cliff-edge",
			title = "8. Cliff edge",
			caption = string.format(
				"Great cliff lip %d studs from the platform; ledges step down to the abyss at %d.",
				math.floor(lipRadius - platform),
				S.ABYSS_Y
			),
			position = polar(cliffAngle - 9, lipRadius - 6, lipY + 26),
			target = polar(cliffAngle + 7, lipRadius + 70, -250),
			fov = 70,
			avatars = { { position = avatar, yaw = yawFacing(avatar, polar(cliffAngle, lipRadius + 100, 0)) } },
		}
	end)(),
	{
		id = "10-stall-turnaround",
		title = "Central stall: base model turnaround",
		caption = "Generic master stall (blue shown). Same geometry for all four; only the canopy colour changes.",
		turnaround = "CentralStall_Blue",
		width = 1600,
		height = 1000,
	},
	{
		id = "11-central-market",
		title = "Central market",
		caption = "Four stalls face the statue (ghost = space reserved for the imported FBX, up to 26 studs tall).",
		position = polar(180, 58, 26),
		target = { 0, 7, 0 },
		fov = 62,
		ghostStatue = true,
		avatars = { { position = polar(180, 14, 0), yaw = 0 } },
	},
	{
		id = "09-far-side",
		title = "9. Far side view",
		caption = "Hub on its high shelf, the stepped drop and the abyss. Haze reduced for review.",
		position = polar(farAngle, 720, -60),
		target = { 0, -150, 0 },
		fov = 58,
		fogScale = 0.5,
	},
}

local scene = {
	floorY = H.FLOOR_Y,
	parts = parts,
	lights = lights,
	depthLighting = depthLighting,
	plots = plots,
	gates = gates,
	stalls = stallFrames,
	statueZone = statueZone,
	views = views,
}
fs.writeFile(output, serde.encode("json", scene))
print(string.format("Wrote %s: %d parts, %d lights, %d views", output, #parts, #lights, #views))
