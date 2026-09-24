-- Turns SeabedShape into blocky, studded Roblox terrain.
-- Every grid cell is a column; equal neighbouring columns are merged into single parts.
-- Caves and overhangs are cut into the great cliff, and a ring of distant massifs closes
-- the basin so the world never ends in a flat boundary wall.

local Util = require(script.Parent.Util)

local SeabedBuilder = {}

local ZONE_FOLDERS = {
	ShallowShelf = "1_ShallowShelf",
	GentleSlope = "2_GentleSlope",
	BrokenShelves = "3_BrokenShelves",
	CliffApproach = "4_CliffApproach",
	GreatCliff = "5_GreatCliff",
	Abyss = "6_Abyss",
}

local CHUNKY_ZONES = { BrokenShelves = true, CliffApproach = true, Abyss = true }

local CAVE_HEIGHT = 14
local CAVE_ROOF_MIN = 6
local OVERHANG_THICKNESS = 6
local FACE_DROP = 30 -- height difference that counts as the cliff face

export type Ground = {
	heightAt: (x: number, z: number) -> number,
	slopeAt: (x: number, z: number) -> number,
	zoneAt: (x: number, z: number) -> string,
	isOpen: (x: number, z: number) -> boolean,
	cell: number,
}

function SeabedBuilder.build(parent: Instance, Config, shape): Ground
	local S, H = Config.Seabed, Config.Hub
	local rockRamp, sandRamp = Config.RockRamp, Config.SandRamp
	local seabed = Util.folder("Seabed", parent)
	local folders = {}
	for zone, name in ZONE_FOLDERS do
		folders[zone] = Util.folder(name, seabed)
	end

	local cell = S.CELL
	local half = S.FINE_HALF_EXTENT
	local n = math.floor(2 * half / cell)
	local skipRadius = H.PLATFORM_RADIUS - 6
	local outsideY = S.ABYSS_Y - 20 -- keep every part above Roblox's -500 destroy height

	local function index(ix: number, iz: number): number
		return ix * n + iz + 1
	end
	local function centre(ix: number, iz: number): (number, number)
		return -half + (ix + 0.5) * cell, -half + (iz + 0.5) * cell
	end
	local function cellAt(x: number, z: number): number?
		local ix = math.floor((x + half) / cell)
		local iz = math.floor((z + half) / cell)
		if ix < 0 or iz < 0 or ix >= n or iz >= n then
			return nil
		end
		return index(ix, iz)
	end

	-- 1. Sample the surface. Beyond the gentle slope, 2x2 cell blocks share one sample so
	-- the deeper terrain reads as chunkier shelves and needs far fewer parts.
	local tops, zones = {}, {}
	for ix = 0, n - 1 do
		for iz = 0, n - 1 do
			local x, z = centre(ix, iz)
			local i = index(ix, iz)
			if math.sqrt(x * x + z * z) < skipRadius then
				tops[i], zones[i] = S.SEABED_Y, "Platform"
			else
				local bx = -half + (ix - ix % 2 + 1) * cell
				local bz = -half + (iz - iz % 2 + 1) * cell
				local blockTop, blockZone = shape:heightAt(bx, bz)
				if CHUNKY_ZONES[blockZone] then
					tops[i], zones[i] = blockTop, blockZone
				else
					tops[i], zones[i] = shape:heightAt(x, z)
					-- Cells straddling the stone base still need seabed under their outer half.
					if zones[i] == "Platform" then
						zones[i] = "ShallowShelf"
					end
				end
			end
		end
	end

	-- 2. Find the great cliff face along a compass direction.
	local function findFace(angle: number): (number?, number?, Vector3?)
		local dir = Util.dir(angle)
		local lip = H.PLATFORM_RADIUS + shape:lipDistance(angle)
		local previous = nil
		for r = lip - 40, lip + 40, 2 do
			local i = cellAt(dir.X * r, dir.Z * r)
			if i and previous and i ~= previous and tops[previous] - tops[i] >= FACE_DROP then
				return previous, i, dir * (r - 2)
			end
			previous = i
		end
		return nil, nil, nil
	end

	local caves, overhangs = {}, {}
	for _, angle in S.CAVE_ANGLES do
		local face, outside, facePoint = findFace(angle)
		if face and outside and facePoint then
			local floorY = tops[outside]
			local ceilY = floorY + CAVE_HEIGHT
			local dir = Util.dir(angle)
			local side = Vector3.new(-dir.Z, 0, dir.X)
			-- Half-cell steps so diagonal tunnels stay connected.
			for step = 0, 7 do
				for lateral = -1, 1 do
					local p = facePoint - dir * (step * cell / 2) + side * (lateral * cell)
					local i = cellAt(p.X, p.Z)
					if i and tops[i] - ceilY >= CAVE_ROOF_MIN then
						caves[i] = { floor = floorY, ceil = ceilY }
					end
				end
			end
		end
	end
	for _, angle in S.OVERHANG_ANGLES do
		local face, _, facePoint = findFace(angle)
		if face and facePoint then
			local topY = tops[face]
			local dir = Util.dir(angle)
			local side = Vector3.new(-dir.Z, 0, dir.X)
			for lateral = -1.5, 1.5, 0.5 do
				local p = facePoint + dir * cell + side * (lateral * cell)
				local i = cellAt(p.X, p.Z)
				if i and not caves[i] and tops[i] <= topY - FACE_DROP then
					overhangs[i] = { bottom = topY - OVERHANG_THICKNESS, top = topY }
				end
			end
		end
	end

	-- 3. Lowest visible level of each column, so neighbours know how far down to reach.
	local function floorOf(i: number): number
		local cave = caves[i]
		return if cave then cave.floor else tops[i]
	end
	local function neighbourFloor(ix: number, iz: number): number
		if ix < 0 or iz < 0 or ix >= n or iz >= n then
			return outsideY
		end
		return floorOf(index(ix, iz))
	end

	local bottoms, slopes, keys = {}, {}, {}
	for ix = 0, n - 1 do
		for iz = 0, n - 1 do
			local i = index(ix, iz)
			local lowest = floorOf(i)
			local slope = 0
			for _, offset in { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } } do
				local nf = neighbourFloor(ix + offset[1], iz + offset[2])
				lowest = math.min(lowest, nf)
				slope = math.max(slope, math.abs(tops[i] - nf))
			end
			bottoms[i] = lowest - 2
			slopes[i] = slope
		end
	end

	-- 4. Colour: sand on level ground, rock on faces and rocky patches, blended by depth.
	local colours = {}
	for ix = 0, n - 1 do
		for iz = 0, n - 1 do
			local i = index(ix, iz)
			local zone = zones[i]
			local x, z = centre(ix, iz)
			local patch = math.noise(x / 40 + 0.31, z / 40 + 0.77, 4.2) * 2
			local rocky = slopes[i] >= 6
				or zone == "GreatCliff"
				or ((zone == "BrokenShelves" or zone == "CliffApproach") and patch > 0.35)
				or (zone == "GentleSlope" and patch > 0.6)
			local colour = Util.ramp(if rocky then rockRamp else sandRamp, tops[i])
			colours[i] = colour
			-- The abyss floor itself comes from the coarse grid below.
			if zone ~= "Platform" and zone ~= "Abyss" and not caves[i] and not overhangs[i] then
				keys[i] = string.format(
					"%s|%g|%d,%d,%d",
					zone,
					tops[i],
					math.floor(colour.R * 255 + 0.5),
					math.floor(colour.G * 255 + 0.5),
					math.floor(colour.B * 255 + 0.5)
				)
			end
		end
	end

	local function column(name: string, zone: string, x: number, z: number, w: number, d: number, bottom: number, top: number, colour: Color3)
		Util.part({
			name = name,
			size = Vector3.new(w, top - bottom, d),
			cframe = CFrame.new(x, (top + bottom) / 2, z),
			color = colour,
			studs = "all",
			parent = folders[zone],
		})
	end

	-- 5. Greedy-merge equal columns into rectangles.
	local used = {}
	for ix = 0, n - 1 do
		for iz = 0, n - 1 do
			local i = index(ix, iz)
			local key = keys[i]
			if key and not used[i] then
				local depthCells = 1
				while iz + depthCells < n do
					local j = index(ix, iz + depthCells)
					if keys[j] ~= key or used[j] then
						break
					end
					depthCells += 1
				end
				local widthCells = 1
				while ix + widthCells < n do
					local ok = true
					for k = 0, depthCells - 1 do
						local j = index(ix + widthCells, iz + k)
						if keys[j] ~= key or used[j] then
							ok = false
							break
						end
					end
					if not ok then
						break
					end
					widthCells += 1
				end
				local bottom = math.huge
				for a = 0, widthCells - 1 do
					for b = 0, depthCells - 1 do
						local j = index(ix + a, iz + b)
						used[j] = true
						bottom = math.min(bottom, bottoms[j])
					end
				end
				local x0, z0 = -half + ix * cell, -half + iz * cell
				column(
					"Seabed",
					zones[i],
					x0 + widthCells * cell / 2,
					z0 + depthCells * cell / 2,
					widthCells * cell,
					depthCells * cell,
					bottom,
					tops[i],
					colours[i]
				)
			end
		end
	end

	-- 6. Cave and overhang cells are split columns.
	for ix = 0, n - 1 do
		for iz = 0, n - 1 do
			local i = index(ix, iz)
			local x, z = centre(ix, iz)
			local cave, overhang = caves[i], overhangs[i]
			if cave then
				local rock = Util.ramp(rockRamp, cave.floor)
				column("CaveFloor", zones[i], x, z, cell, cell, bottoms[i], cave.floor, rock)
				column("CaveRoof", zones[i], x, z, cell, cell, cave.ceil, tops[i], colours[i])
			elseif overhang then
				column("CliffBase", zones[i], x, z, cell, cell, bottoms[i], tops[i], colours[i])
				column("Overhang", "GreatCliff", x, z, cell, cell, overhang.bottom, overhang.top, Util.ramp(rockRamp, overhang.top))
			end
		end
	end

	-- 7. Coarse abyss floor across the whole basin. Cells hidden under the shelf are
	-- skipped; the rest lie beneath the cliff scree and stretch out to the massifs.
	local coarse = S.COARSE_CELL
	local oceanHalf = Config.Ocean.HALF_EXTENT
	local coarseCount = math.floor(2 * oceanHalf / coarse)
	local maxRun = math.floor(2048 / coarse) -- Roblox parts cap at 2048 studs per axis
	local nearestLip = math.huge
	for angle = 0, 359.5, 0.5 do
		nearestLip = math.min(nearestLip, shape:lipDistance(angle))
	end
	local hiddenRadius = H.PLATFORM_RADIUS + nearestLip - 16
	local coarseTops = {}
	for ix = 0, coarseCount - 1 do
		for iz = 0, coarseCount - 1 do
			local x = -oceanHalf + (ix + 0.5) * coarse
			local z = -oceanHalf + (iz + 0.5) * coarse
			local farCorner = math.sqrt((math.abs(x) + coarse / 2) ^ 2 + (math.abs(z) + coarse / 2) ^ 2)
			if farCorner > hiddenRadius then
				local dip = math.noise(x / 300 + 0.4, z / 300 + 0.9, 7.7) * 2
				coarseTops[ix * coarseCount + iz] = Util.quantize(S.ABYSS_Y + dip * 12, 8)
			end
		end
	end
	local coarseUsed = {}
	local function coarseFree(ix: number, iz: number, top: number): boolean
		local j = ix * coarseCount + iz
		return coarseTops[j] == top and not coarseUsed[j]
	end
	for ix = 0, coarseCount - 1 do
		for iz = 0, coarseCount - 1 do
			local top = coarseTops[ix * coarseCount + iz]
			if top and not coarseUsed[ix * coarseCount + iz] then
				local d = 1
				while iz + d < coarseCount and d < maxRun and coarseFree(ix, iz + d, top) do
					d += 1
				end
				local w = 1
				while ix + w < coarseCount and w < maxRun do
					local ok = true
					for k = 0, d - 1 do
						if not coarseFree(ix + w, iz + k, top) then
							ok = false
							break
						end
					end
					if not ok then
						break
					end
					w += 1
				end
				for a = 0, w - 1 do
					for b = 0, d - 1 do
						coarseUsed[(ix + a) * coarseCount + iz + b] = true
					end
				end
				column(
					"AbyssFloor",
					"Abyss",
					-oceanHalf + (ix + w / 2) * coarse,
					-oceanHalf + (iz + d / 2) * coarse,
					w * coarse,
					d * coarse,
					S.ABYSS_Y - 24,
					top,
					Util.ramp(sandRamp, top)
				)
			end
		end
	end

	-- 8. Basin rim: a continuous ring of stepped cliffs far out in the haze. Each tier
	-- steps back as it rises and the top tier breaks the water surface, so the world
	-- closes naturally and nobody can swim past the edge of the water.
	local massifs = Util.folder("BasinRim", folders.Abyss)
	local rng = Util.newRng(Config.SEED + 19)
	local count = 36
	local surface = Config.Ocean.SURFACE_Y
	for k = 0, count - 1 do
		local angle = k * 360 / count + rng.range(-1, 1)
		local radius = S.MASSIF_RADIUS + rng.range(-25, 25)
		local tiers = {
			-- Widths exceed the widest gap between neighbours, so every tier is continuous.
			{ w = rng.range(310, 340), d = rng.range(200, 240), top = rng.range(-300, -220) },
			{ w = rng.range(270, 300), d = rng.range(150, 180), top = rng.range(-120, -40) },
			{ w = rng.range(250, 275), d = rng.range(110, 140), top = rng.range(60, 140) },
			{ w = rng.range(240, 265), d = rng.range(70, 100), top = surface + rng.range(12, 40) },
		}
		local bottom = S.ABYSS_Y - 24
		for t, tier in tiers do
			local top = tier.top
			local r = radius + (t - 1) * 24
			Util.part({
				name = "Massif",
				size = Vector3.new(tier.w, top - bottom, tier.d),
				cframe = Util.radialFrame(angle, r, (top + bottom) / 2),
				color = Util.ramp(rockRamp, math.min(top, -150)),
				studs = "all",
				parent = massifs,
			})
			bottom = top - 1
		end
	end

	-- Ground queries for decor placement.
	local ground = {} :: any
	ground.cell = cell
	function ground.heightAt(x: number, z: number): number
		local r = math.sqrt(x * x + z * z)
		if r < H.SKIRT.OUTER then
			return H.FLOOR_Y + H.SKIRT.TOP
		elseif r < H.PLATFORM_RADIUS then
			return H.FLOOR_Y + H.BASE.TOP - 0.5
		end
		local i = cellAt(x, z)
		return if i then tops[i] else S.ABYSS_Y
	end
	function ground.slopeAt(x: number, z: number): number
		local i = cellAt(x, z)
		return if i then slopes[i] else 0
	end
	function ground.zoneAt(x: number, z: number): string
		local i = cellAt(x, z)
		return if i then zones[i] else "Abyss"
	end
	function ground.isOpen(x: number, z: number): boolean
		local i = cellAt(x, z)
		return i ~= nil and not caves[i] and not overhangs[i]
	end
	return ground
end

return SeabedBuilder
