-- Acceptance checks for the six-plaza starter hub revision.
-- Builds the world with the real builder modules against the mock API, then verifies the
-- review checklist on the resulting geometry.
--   lune run tools/check-world.luau
-- Exits non-zero if any check fails.

local fs = require("@lune/fs")
local process = require("@lune/process")

local Loader = require("./mock/loader")
local Scene = require("./mock/scene")
local roblox = Loader.roblox
local Vector3 = roblox.Vector3

local ROOT = string.gsub((string.gsub(process.cwd, "/$", "")), "/tools$", "")
if not fs.isDir(ROOT .. "/src") then
	ROOT = string.gsub(process.cwd, "/$", "") .. "/dive-for-eggs"
end

local world, Config = Loader.buildWorld(ROOT .. "/src")
local H, B, S = Config.Hub, Config.Bubble, Config.Seabed
local F = H.FLOOR_Y
local hub = world.Hub

local failures = 0
local function check(ok: boolean, label: string, detail: string?)
	print(string.format("%s  %s%s", if ok then "PASS" else "FAIL", label, if detail then "  (" .. detail .. ")" else ""))
	if not ok then
		failures += 1
	end
end

local function radius(v): number
	return math.sqrt(v.X * v.X + v.Z * v.Z)
end

local function angleOf(v): number
	return math.deg(math.atan2(v.X, -v.Z)) % 360
end

local function angleDelta(a: number, b: number): number
	return math.abs((a - b + 180) % 360 - 180)
end

local allParts = Scene.parts(world)
local hubParts = Scene.parts(hub)

------------------------------------------------------------------------ plots and pads
local plots = hub.Plots:GetChildren()
check(#plots == 6, "exactly 6 player plazas", #plots .. " plots")

local pads, anchors, surfaces = 0, {}, {}
for _, plot in plots do
	local pad = plot:FindFirstChild("AquariumPad")
	if pad then
		pads += 1
		table.insert(anchors, pad.AquariumAnchor)
		table.insert(surfaces, pad.PadSurface)
	end
end
check(pads == 6, "exactly 6 aquarium foundation pads", pads .. " pads")

local ratiosOk, facingOk, tangentOk = true, true, true
local padAngles, ratioText = {}, {}
for _, anchor in anchors do
	local size = anchor.Size
	local ratio = size.X / size.Z
	table.insert(ratioText, string.format("%gx%g", size.X, size.Z))
	if math.abs(ratio - 1.5) > 0.1 then
		ratiosOk = false
	end
	local c = anchor.CFrame
	local toCentre = Vector3.new(-c.Position.X, 0, -c.Position.Z).Unit
	if c.LookVector:Dot(toCentre) < 0.999 then
		facingOk = false
	end
	if math.abs(c.RightVector:Dot(toCentre)) > 0.001 then
		tangentOk = false
	end
	table.insert(padAngles, angleOf(c.Position))
end
check(ratiosOk, "pads are ~1.5:1 rectangles", table.concat(ratioText, ", "))
check(tangentOk, "pad width runs along the circumference, depth runs radially")
check(facingOk, "every pad's glass side (LookVector) faces the hub centre")

table.sort(padAngles)
local spacingOk = true
for i = 1, #padAngles do
	local nextAngle = padAngles[i % #padAngles + 1] + (if i == #padAngles then 360 else 0)
	if math.abs(nextAngle - padAngles[i] - 60) > 0.01 then
		spacingOk = false
	end
end
check(spacingOk, "pads are evenly spaced 60 degrees apart", table.concat(padAngles, ", "))

local squareFree = true
for _, surface in surfaces do
	local ratio = surface.Size.X / surface.Size.Z
	if math.abs(ratio - 1) < 0.25 then
		squareFree = false
	end
end
check(squareFree, "no square pads remain")

local dividers = 0
for _, part in hub.FloorPattern:GetChildren() do
	if part.Name == "SectorDivider" then
		dividers += 1
	end
end
check(dividers == 6, "six radial sector dividers", dividers .. " dividers")

------------------------------------------------------------------------ plaza, stalls and interior
local StallBuilder = Loader.require(roblox.game:GetService("ServerScriptService").DiveWorldBuild.StallBuilder)
local stallsFolder = hub:FindFirstChild("CentralStalls")
local statueRadius = StallBuilder.statueRadius(Config)

local function inStalls(part): boolean
	return stallsFolder ~= nil and part:IsDescendantOf(stallsFolder)
end

-- The middle of the plaza is reserved for the imported fish statue.
local statueZoneBlockers = {}
for _, part in allParts do
	-- The bubble shell's bounding box spans the plaza, but the shell itself passes
	-- 150 studs overhead and has no collision.
	if part.Transparency < 1 and part.Name ~= "AirBubble" then
		local centre, half = Scene.aabb(part)
		local nearest = math.max(0, radius(centre) - math.max(half.X, half.Z))
		if nearest < statueRadius and centre.Y + half.Y > F + 0.25 and centre.Y - half.Y < F + 60 then
			table.insert(statueZoneBlockers, part:GetFullName())
		end
	end
end
check(
	#statueZoneBlockers == 0,
	"statue zone in the middle of the plaza is clear",
	string.format("radius %.1f, %d blockers", statueRadius, #statueZoneBlockers)
)

local clutter = {}
for _, part in hubParts do
	if part.Transparency < 1 and not inStalls(part) then
		local centre, half = Scene.aabb(part)
		if radius(centre) + math.max(half.X, half.Z) < 118 and centre.Y + half.Y > F + 1 then
			table.insert(clutter, part:GetFullName())
		end
	end
end
check(#clutter == 0, "hub interior: only the four stalls rise above the floor", #clutter .. " other items")

local stalls = if stallsFolder then stallsFolder:GetChildren() else {}
local expectedColours = { Blue = true, Red = true, Yellow = true, Green = true }
local namesOk = #stalls == 4
for _, stall in stalls do
	local colour = stall:GetAttribute("StallColor")
	if stall.Name ~= "CentralStall_" .. tostring(colour) or not expectedColours[colour] then
		namesOk = false
	end
	expectedColours[colour] = nil
end
check(namesOk, "exactly 4 stalls: blue, red, yellow and green", #stalls .. " stalls")

-- Geometry signature relative to each stall's pivot; colour excluded for canopy stripes.
local function signature(model, withCanopyColour: boolean): string
	local rows = {}
	local inverse = model:GetPivot():Inverse()
	for _, part in Scene.parts(model) do
		local rel = inverse * part.CFrame
		local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = rel:GetComponents()
		local colour = part.Color:ToHex()
		if part:GetAttribute("CanopyStripe") == "Color" and not withCanopyColour then
			colour = "canopy"
		end
		local values = { x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22, part.Size.X, part.Size.Y, part.Size.Z }
		for i, v in values do
			-- Round first so -0.0001 and 0.0001 compare equal.
			values[i] = string.format("%.3f", math.floor(v * 1000 + 0.5) / 1000 + 0)
		end
		table.insert(rows, part.Name .. "|" .. table.concat(values, ",") .. "|" .. colour .. "|" .. part.Material.Name)
	end
	table.sort(rows)
	return table.concat(rows, "\n")
end

local master = roblox.game:GetService("ServerStorage"):FindFirstChild("DiveWorldTemplates")
master = master and master:FindFirstChild("CentralStall_Master")
local masterSignature = master and signature(master, false)
local identical = master ~= nil and #stalls == 4
for _, stall in stalls do
	if signature(stall, false) ~= masterSignature then
		identical = false
	end
end
check(identical, "all four stalls are exact copies of CentralStall_Master (ServerStorage)")

local P = Config.Palette
local canopyOk = #stalls == 4
for _, stall in stalls do
	local want = P.Canopy[stall:GetAttribute("StallColor")]
	local coloured, white = 0, 0
	for _, part in Scene.parts(stall) do
		local stripe = part:GetAttribute("CanopyStripe")
		if stripe == "Color" then
			coloured += 1
			canopyOk = canopyOk and want ~= nil and part.Color:ToHex() == want:ToHex()
		elseif stripe == "White" then
			white += 1
			canopyOk = canopyOk and part.Color:ToHex() == P.CanopyWhite:ToHex()
		end
	end
	canopyOk = canopyOk and coloured == 4 and white == 3
end
check(canopyOk, "canopies are colour/white stripes, the only difference between stalls")

local textFree = true
for _, stall in stalls do
	for _, d in stall:GetDescendants() do
		if d.ClassName == "SurfaceGui" or d.ClassName == "TextLabel" or d.ClassName == "Decal" or d.ClassName == "BillboardGui" then
			textFree = false
		end
	end
end
check(textFree, "stalls carry no header, text, logo or products")

local facingOk, angles = #stalls == 4, {}
for _, stall in stalls do
	local pivot = stall:GetPivot()
	local toCentre = Vector3.new(-pivot.Position.X, 0, -pivot.Position.Z).Unit
	facingOk = facingOk and pivot.LookVector:Dot(toCentre) > 0.999 and math.abs(pivot.Position.Y - F) < 1e-6
	table.insert(angles, math.floor(angleOf(pivot.Position) + 0.5))
end
table.sort(angles)
check(
	facingOk and table.concat(angles, ",") == "45,135,225,315",
	"stall counters all face the statue, evenly spaced 90 degrees apart",
	table.concat(angles, ", ")
)

-- Footprints: nothing may overlap another stall, leave the plaza, or reach the floor lines.
local function footprints(model)
	local out = {}
	for _, part in Scene.parts(model) do
		local centre, half = Scene.aabb(part)
		table.insert(out, { centre = centre, half = half, part = part })
	end
	return out
end
local function boxesOverlap(a, b): boolean
	return math.abs(a.centre.X - b.centre.X) < a.half.X + b.half.X
		and math.abs(a.centre.Z - b.centre.Z) < a.half.Z + b.half.Z
		and math.abs(a.centre.Y - b.centre.Y) < a.half.Y + b.half.Y
end
local stallBoxes = {}
for i, stall in stalls do
	stallBoxes[i] = footprints(stall)
end
local overlaps = 0
for i = 1, #stalls do
	for j = i + 1, #stalls do
		for _, a in stallBoxes[i] do
			for _, b in stallBoxes[j] do
				if boxesOverlap(a, b) then
					overlaps += 1
				end
			end
		end
	end
end
check(overlaps == 0, "stalls do not overlap each other")

local ringInner = H.PLAZA_RADIUS - H.PLAZA_RING_WIDTH / 2
local outside, nearest, farthestGround = 0, math.huge, 0
for _, boxes in stallBoxes do
	for _, box in boxes do
		local r = Scene.farthestCorner(box.part, 0, 0)
		-- The walking ring is measured at walking height; the canopy overhangs above heads.
		if box.centre.Y - box.half.Y < F + 6 then
			nearest = math.min(nearest, Scene.footprintDistance(box.part, 0, 0))
		end
		-- Posts, counter and rails stand on the floor; the canopy only overhangs.
		if box.part:GetAttribute("CanopyStripe") == nil then
			farthestGround = math.max(farthestGround, r)
			if r > ringInner then
				outside += 1
			end
		elseif r > H.PLAZA_RADIUS + 1 then
			outside += 1
		end
	end
end
check(
	outside == 0,
	"stalls stand inside the plaza ring, clear of the radial floor lines",
	string.format("farthest post/counter corner %.1f of ring %.1f", farthestGround, ringInner)
)
check(
	nearest >= statueRadius + Config.Statue.WALK_RING - 0.01,
	"walking ring of at least 6 studs between the statue zone and the stall counters",
	string.format("statue zone %.1f, nearest stall part %.1f", statueRadius, nearest)
)

local blockedGates = {}
for _, gateAngle in H.GATE_ANGLES do
	local a = math.rad(gateAngle)
	for r = 0, H.WALL_INNER_RADIUS, 1 do
		for _, lateral in { -2, 0, 2 } do
			local x = math.sin(a) * r + math.cos(a) * lateral
			local z = -math.cos(a) * r + math.sin(a) * lateral
			for _, boxes in stallBoxes do
				for _, box in boxes do
					if box.centre.Y - box.half.Y < F + 6 and Scene.covers(box.part, x, z) then
						blockedGates[gateAngle] = true
					end
				end
			end
		end
	end
end
check(next(blockedGates) == nil, "straight 4-stud lanes from the statue to all four gates stay open")

local counterTop, roofTop = 0, 0
if stalls[1] then
	for _, part in Scene.parts(stalls[1]) do
		if part.Name == "CounterFront" then
			counterTop = Scene.top(part) - F
		elseif part.Name == "CanopyStripe" then
			roofTop = math.max(roofTop, Scene.top(part) - F)
		end
	end
end
check(
	counterTop >= 3 and counterTop <= 4 and roofTop >= 9 and roofTop <= 12,
	"stall scale fits a 5-stud avatar (counter about chest height, roof about 2 avatars)",
	string.format("counter top %.2f, roof top %.2f", counterTop, roofTop)
)

local lanterns, lightCount, innerLanterns = 0, 0, 0
for _, d in world:GetDescendants() do
	if d.ClassName == "Model" and d.Name == "Lantern" then
		lanterns += 1
		if radius(d.LanternGlow.Position) < 118 then
			innerLanterns += 1
		end
	elseif d.ClassName == "PointLight" then
		lightCount += 1
	end
end
check(innerLanterns == 0, "no freestanding lanterns inside the hub", lanterns .. " lanterns, all on walls or gates")

local forbidden = {}
for _, part in allParts do
	local name = string.lower(part.Name)
	for _, word in { "fountain", "orb", "pedestal", "planter", "monument", "bridge", "ladder", "bench", "crate", "sign", "sonar", "logo" } do
		if string.find(name, word, 1, true) then
			table.insert(forbidden, part:GetFullName())
		end
	end
end
check(#forbidden == 0, "no fountain/bridge/ladder/bench/sign/sonar/logo parts generated", #forbidden .. " found")

local aquariums = 0
for _, part in allParts do
	if part.Material.Name == "Glass" and radius(part.Position) < H.WALL_INNER_RADIUS then
		aquariums += 1
	end
end
check(aquariums == 0, "no aquariums built yet (no glass inside the hub)")

------------------------------------------------------------------------ solid floor
local floorStrips = {}
for _, part in hub.Floor:GetChildren() do
	if part.Name == "Floor" then
		table.insert(floorStrips, part)
	end
end
local holes, samples = 0, 0
for x = -H.WALL_INNER_RADIUS, H.WALL_INNER_RADIUS, 2 do
	for z = -H.WALL_INNER_RADIUS, H.WALL_INNER_RADIUS, 2 do
		if math.sqrt(x * x + z * z) < H.WALL_INNER_RADIUS - 0.5 then
			samples += 1
			local covered = false
			for _, strip in floorStrips do
				if Scene.covers(strip, x, z) and math.abs(Scene.top(strip) - F) < 1e-6 then
					covered = true
					break
				end
			end
			if not covered then
				holes += 1
			end
		end
	end
end
check(holes == 0, "floor is solid wall-to-wall, no central hole", samples .. " samples, " .. holes .. " uncovered")

------------------------------------------------------------------------ floor colour mix
local P = Config.Palette
local function colourKey(c)
	return c:ToHex()
end
local classes = {
	[colourKey(P.Floor)] = "cream",
	[colourKey(P.FloorLight)] = "cream",
	[colourKey(P.Green)] = "green",
	[colourKey(P.Trim)] = "trim",
	[colourKey(P.PadSurface)] = "pad",
	[colourKey(P.PadFrame)] = "pad",
	[colourKey(P.PadFront)] = "pad",
}
local layer = {}
for _, part in floorStrips do
	table.insert(layer, part)
end
for _, part in Scene.parts(hub.FloorPattern) do
	table.insert(layer, part)
end
for _, part in Scene.parts(hub.Plots) do
	if part.Transparency < 1 then
		table.insert(layer, part)
	end
end
local tally = { cream = 0, green = 0, trim = 0, pad = 0 }
for x = -H.WALL_INNER_RADIUS, H.WALL_INNER_RADIUS, 2 do
	for z = -H.WALL_INNER_RADIUS, H.WALL_INNER_RADIUS, 2 do
		if math.sqrt(x * x + z * z) < H.WALL_INNER_RADIUS - 0.5 then
			local best, bestTop = nil, -math.huge
			for _, part in layer do
				local top = Scene.top(part)
				if top > bestTop and Scene.covers(part, x, z) then
					best, bestTop = part, top
				end
			end
			local class = best and classes[colourKey(best.Color)] or "cream"
			tally[class] += 1
		end
	end
end
local open = tally.cream + tally.green + tally.trim
local creamPct = 100 * tally.cream / open
local greenPct = 100 * tally.green / open
check(
	creamPct >= 70 and creamPct <= 85 and greenPct >= 10 and greenPct <= 20,
	"open floor is mostly cream with 10-20% green",
	string.format(
		"cream %.1f%%, green %.1f%%, trim %.1f%% of open floor; pads cover %.1f%% of the hub",
		creamPct,
		greenPct,
		100 * tally.trim / open,
		100 * tally.pad / (open + tally.pad)
	)
)

------------------------------------------------------------------------ gates and bubble
local gates = hub.Gates:GetChildren()
local gateAngles, curtainsOk, openingsClear = {}, true, true
for _, gate in gates do
	table.insert(gateAngles, gate:GetAttribute("Angle"))
	local curtain = gate.WaterCurtain
	if curtain.CanCollide or curtain.Material.Name == "Neon" or curtain.Transparency < 0.3 then
		curtainsOk = false
	end
	if math.abs(radius(curtain.Position) - B.MEMBRANE_RADIUS) > 0.01 then
		curtainsOk = false
	end
	-- Nothing collidable inside the walk-through opening above the threshold.
	local angle = gate:GetAttribute("Angle")
	for _, part in allParts do
		if part.CanCollide and part.Name ~= "GateThreshold" and part.Name ~= "Floor" then
			for _, probe in { { 0, 2 }, { -5, 2 }, { 5, 2 }, { 0, 9 }, { 0, 15 } } do
				for r = 121, 137, 2 do
					local a = math.rad(angle)
					local dirX, dirZ = math.sin(a), -math.cos(a)
					local x = dirX * r + dirZ * -probe[1]
					local z = dirZ * r + dirX * probe[1]
					local centre, half = Scene.aabb(part)
					local y = F + probe[2]
					if
						math.abs(x - centre.X) < half.X
						and math.abs(z - centre.Z) < half.Z
						and math.abs(y - centre.Y) < half.Y
						and Scene.covers(part, x, z)
					then
						openingsClear = false
					end
				end
			end
		end
	end
end
table.sort(gateAngles)
check(#gates == 4 and table.concat(gateAngles, ",") == "0,90,180,270", "four waterfall gates at the cardinal directions", table.concat(gateAngles, ", "))
check(curtainsOk, "gate curtains are see-through water membranes (no collision, not neon) on the bubble line")
check(openingsClear, "gate openings are clear to walk/swim through")

local bubbles = {}
for _, part in allParts do
	if part.Name == "AirBubble" then
		table.insert(bubbles, part)
	end
end
local bubble = bubbles[1]
local mesh = bubble and bubble:FindFirstChildOfClass("SpecialMesh")
check(
	#bubbles == 1
		and mesh ~= nil
		and mesh.MeshType.Name == "Sphere"
		and bubble.Size.X / 2 >= H.WALL_INNER_RADIUS + H.WALL_THICKNESS
		and bubble.Size.Y / 2 >= bubble.Size.X / 2
		and bubble.Transparency >= 0.8
		and not bubble.CanCollide,
	"one smooth transparent bubble covers the whole hub",
	bubble and string.format("radius %g, height %g, transparency %g", bubble.Size.X / 2, bubble.Size.Y / 2, bubble.Transparency) or "missing"
)

-- Terrain: ocean water first, then an air pocket matching the bubble.
local ops = roblox.terrainOps
local waterFill, carveOk, carvedAfterFill = 0, true, true
local sawCarve = false
for _, op in ops do
	if op.material == "Water" then
		waterFill += op.size.X * op.size.Y * op.size.Z
		if sawCarve then
			carvedAfterFill = false
		end
	elseif op.material == "Air" then
		sawCarve = true
		local h = op.cframe.Position.Y - F
		if h >= 0 and h <= 20 and op.radius < H.WALL_INNER_RADIUS + H.WALL_THICKNESS then
			carveOk = false
		end
	end
end
local oceanVolume = (2 * Config.Ocean.HALF_EXTENT) ^ 2 * (Config.Ocean.SURFACE_Y - Config.Ocean.BOTTOM_Y)
check(math.abs(waterFill - oceanVolume) / oceanVolume < 0.01, "ocean is filled with terrain water")
check(carveOk and carvedAfterFill and sawCarve, "hub interior is carved dry (air pocket reaches the gate curtains)")

------------------------------------------------------------------------ spawn
local spawn = hub:FindFirstChild("HubSpawn")
local spawnOk = false
if spawn then
	local c = spawn.CFrame
	local toCentre = Vector3.new(-c.Position.X, 0, -c.Position.Z).Unit
	spawnOk = c.LookVector:Dot(toCentre) > 0.999 and radius(c.Position) < H.WALL_INNER_RADIUS and math.abs(c.Position.Y + 0.45 - F) < 0.01
end
check(spawnOk, "spawn is on the dry hub floor, facing the centre")

------------------------------------------------------------------------ terrain profile
local seabed = world.Seabed
local heightAt = Scene.heightRaster(seabed, S.CELL, S.FINE_HALF_EXTENT)
local platform = H.PLATFORM_RADIUS
local rays = 72
local bands = { { 0, 40 }, { 40, 100 }, { 100, 180 }, { 180, 230 } }
local bandMeans = { 0, 0, 0, 0 }
local flatSpread, dropRays, steppedRays, maxSingleStep = 0, 0, 0, 0
for k = 0, rays - 1 do
	local a = math.rad(k * 360 / rays + 2.5)
	local dx, dz = math.sin(a), -math.cos(a)
	for b, band in bands do
		local sum, count, lo, hi = 0, 0, math.huge, -math.huge
		for d = band[1] + 2, band[2] - 2, 4 do
			local y = heightAt(dx * (platform + d), dz * (platform + d))
			if y then
				sum += y
				count += 1
				lo, hi = math.min(lo, y), math.max(hi, y)
			end
		end
		bandMeans[b] += sum / count / rays
		if b == 1 then
			flatSpread = math.max(flatSpread, hi - lo)
		end
	end
	-- Walk out through the great cliff.
	local previous, ledges, deepest = nil, {}, 0
	for d = 180, 430, 4 do
		local y = heightAt(dx * (platform + d), dz * (platform + d))
		if y then
			if previous and previous - y > 20 then
				table.insert(ledges, y)
			end
			if previous then
				maxSingleStep = math.max(maxSingleStep, previous - y)
			end
			previous = y
			deepest = math.min(deepest, y)
		end
	end
	if deepest <= S.ABYSS_Y + 20 then
		dropRays += 1
	end
	if #ledges >= 3 then
		steppedRays += 1
	end
end
check(flatSpread <= 3, "terrain is level for the first 40 studs", string.format("max spread %g studs", flatSpread))
check(
	bandMeans[1] > bandMeans[2] and bandMeans[2] > bandMeans[3] and bandMeans[3] > bandMeans[4],
	"terrain gets steadily deeper away from the hub",
	string.format("mean height 0-40: %.0f, 40-100: %.0f, 100-180: %.0f, 180-230: %.0f", table.unpack(bandMeans))
)
check(dropRays == rays, "a huge drop to the abyss exists in every direction", string.format("%d/%d rays reach %d", dropRays, rays, S.ABYSS_Y))
check(steppedRays >= rays * 0.9, "the great cliff is stepped (3+ ledges), not one wall", string.format("%d/%d rays", steppedRays, rays))
check(maxSingleStep <= 130, "no single vertical cliff face taller than 130 studs", string.format("tallest single step %g", maxSingleStep))

local caves, overhangs = 0, 0
for _, part in Scene.parts(seabed) do
	if part.Name == "CaveRoof" then
		caves += 1
	elseif part.Name == "Overhang" then
		overhangs += 1
	end
end
check(caves > 0 and overhangs > 0, "cliff has caves and overhangs", caves .. " cave roof cells, " .. overhangs .. " overhang cells")

local walls = {}
for _, part in allParts do
	local _, half = Scene.aabb(part)
	if half.Y * 2 > 200 and math.max(half.X, half.Z) * 2 > 600 then
		table.insert(walls, part:GetFullName())
	end
end
check(#walls == 0, "no giant boundary wall around the map", #walls .. " wall-like parts")

-- The basin rim must break the water surface all the way round.
local rimTops = {}
for _, part in Scene.parts(seabed) do
	if part.Name == "Massif" and Scene.top(part) > Config.Ocean.SURFACE_Y then
		table.insert(rimTops, part)
	end
end
local rimGaps = 0
for step = 0, 719 do
	local a = math.rad(step / 2)
	local closed = false
	for r = S.MASSIF_RADIUS, S.MASSIF_RADIUS + 140, 4 do
		for _, part in rimTops do
			if Scene.covers(part, math.sin(a) * r, -math.cos(a) * r) then
				closed = true
				break
			end
		end
		if closed then
			break
		end
	end
	if not closed then
		rimGaps += 1
	end
end
check(rimGaps == 0, "basin rim is continuous above the water surface", rimGaps .. " open directions of 720")

local unstudded = 0
for _, part in Scene.parts(seabed) do
	if part.TopSurface.Name ~= "Studs" or part.Material.Name ~= "Plastic" then
		unstudded += 1
	end
end
check(unstudded == 0, "terrain is Roblox stud style (studded plastic blocks)")

------------------------------------------------------------------------ client scripts
local clientDir = ROOT .. "/src/StarterPlayer/StarterPlayerScripts/DiveWorldClient"
local buoyancy = fs.readFile(clientDir .. "/NeutralBuoyancy.client.luau")
check(
	string.find(buoyancy, "VelocityConstraintMode.Line", 1, true) ~= nil and string.find(buoyancy, "LineVelocity = 0", 1, true) ~= nil,
	"neutral buoyancy holds vertical velocity at 0 while idle"
)

------------------------------------------------------------------------ summary
local counts = {}
for _, child in world:GetChildren() do
	local n = 0
	for _, d in child:GetDescendants() do
		if d:IsA("BasePart") then
			n += 1
		end
	end
	if child:IsA("BasePart") then
		n += 1
	end
	table.insert(counts, child.Name .. " " .. n)
end
print(string.format("\nParts: %d total (%s); %d lanterns / %d point lights", #allParts, table.concat(counts, ", "), lanterns, lightCount))
print(if failures == 0 then "All checks passed." else failures .. " check(s) failed.")
process.exit(if failures == 0 then 0 else 1)
