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

------------------------------------------------------------------------ empty centre and interior
local plazaBlockers = {}
for _, part in allParts do
	-- The bubble shell's bounding box spans the plaza, but the shell itself passes
	-- 150 studs overhead and has no collision.
	if part.Transparency < 1 and part.Name ~= "AirBubble" then
		local centre, half = Scene.aabb(part)
		local nearest = math.max(0, radius(centre) - math.max(half.X, half.Z))
		if nearest < H.PLAZA_RADIUS + 2 and centre.Y + half.Y > F + 0.25 and centre.Y - half.Y < F + 60 then
			table.insert(plazaBlockers, part:GetFullName())
		end
	end
end
check(#plazaBlockers == 0, "central plaza has no physical objects", #plazaBlockers .. " blockers " .. table.concat(plazaBlockers, "; "))

local clutter = {}
for _, part in hubParts do
	if part.Transparency < 1 then
		local centre, half = Scene.aabb(part)
		if radius(centre) + math.max(half.X, half.Z) < 118 and centre.Y + half.Y > F + 1 then
			table.insert(clutter, part:GetFullName())
		end
	end
end
check(#clutter == 0, "hub interior: nothing rises more than 1 stud above the floor", #clutter .. " items")

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
	for _, word in { "statue", "fountain", "orb", "pedestal", "planter", "monument", "bridge", "ladder", "support", "bench", "crate", "sign" } do
		if string.find(name, word, 1, true) then
			table.insert(forbidden, part:GetFullName())
		end
	end
end
check(#forbidden == 0, "no statue/fountain/bridge/ladder/support/bench/sign parts", #forbidden .. " found")

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
