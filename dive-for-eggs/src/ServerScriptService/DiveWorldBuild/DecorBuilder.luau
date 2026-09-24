-- Exterior decoration: coral, kelp, rocks and shells around the platform and across the
-- shelf, rock formations on the broken shelves, sparse life on the cliff and dark spires
-- in the abyss. Nothing is placed inside the hub walls.

local Util = require(script.Parent.Util)

local DecorBuilder = {}

local function piece(parent: Instance, name: string, size: Vector3, cframe: CFrame, colour: Color3, solid: boolean?)
	return Util.part({
		name = name,
		size = size,
		cframe = cframe,
		color = colour,
		studs = if solid then "all" else "top",
		collide = if solid then nil else false,
		shadow = solid == true,
		parent = parent,
	})
end

local function yaw(rng): CFrame
	return CFrame.Angles(0, math.rad(rng.int(0, 11) * 15), 0)
end

local function branchCoral(parent: Instance, rng, base: CFrame, colour: Color3, scale: number)
	local model = Util.model("BranchCoral", parent)
	local s = scale
	local stem = rng.range(2, 3.2) * s
	piece(model, "Coral", Vector3.new(1.4 * s, 0.8 * s, 1.4 * s), base * CFrame.new(0, 0.4 * s, 0), colour)
	piece(model, "Coral", Vector3.new(0.9 * s, stem, 0.9 * s), base * CFrame.new(0, 0.8 * s + stem / 2, 0), colour)
	for k = 1, rng.int(2, 4) do
		local armY = 0.8 * s + stem * rng.range(0.35, 0.9)
		local reach = rng.range(1, 1.8) * s
		local arm = base * CFrame.Angles(0, math.rad(k * 90 + rng.range(-20, 20)), 0)
		piece(model, "Coral", Vector3.new(reach, 0.7 * s, 0.7 * s), arm * CFrame.new(reach / 2 + 0.3 * s, armY, 0), colour)
		local tip = rng.range(1, 2.2) * s
		piece(model, "Coral", Vector3.new(0.7 * s, tip, 0.7 * s), arm * CFrame.new(reach + 0.3 * s, armY + tip / 2, 0), colour)
	end
	return model
end

local function tubeCoral(parent: Instance, rng, base: CFrame, colour: Color3, scale: number)
	local model = Util.model("TubeCoral", parent)
	for _ = 1, rng.int(3, 5) do
		local h = rng.range(1.2, 3.5) * scale
		local offset = CFrame.new(rng.range(-1, 1) * scale, h / 2, rng.range(-1, 1) * scale)
		piece(model, "Coral", Vector3.new(0.8, h, 0.8) * scale, base * offset, colour)
	end
	return model
end

local function fanCoral(parent: Instance, rng, base: CFrame, colour: Color3, scale: number)
	local model = Util.model("FanCoral", parent)
	local h = rng.range(2.5, 4) * scale
	piece(model, "Coral", Vector3.new(0.6, 1, 0.6) * scale, base * CFrame.new(0, 0.5 * scale, 0), colour)
	piece(model, "Coral", Vector3.new(h, h * 0.8, 0.25 * scale), base * yaw(rng) * CFrame.new(0, scale + h * 0.4, 0), colour)
	return model
end

local function sponge(parent: Instance, rng, base: CFrame, colour: Color3, scale: number)
	local model = Util.model("Sponge", parent)
	local w = rng.range(1.8, 2.6) * scale
	piece(model, "Coral", Vector3.new(w, 1.4 * scale, w), base * CFrame.new(0, 0.7 * scale, 0), colour)
	piece(model, "Coral", Vector3.new(w * 0.6, 0.8 * scale, w * 0.6), base * CFrame.new(0, 1.8 * scale, 0), colour)
	return model
end

local CORAL_SHAPES = { branchCoral, branchCoral, tubeCoral, fanCoral, sponge }

local function coral(parent: Instance, rng, base: CFrame, palette, scale: number)
	local shape = rng.pick(CORAL_SHAPES)
	return shape(parent, rng, base * yaw(rng), rng.pick(palette), scale)
end

local function kelp(parent: Instance, rng, base: CFrame, height: number, palette)
	local model = Util.model("Kelp", parent)
	local colour = rng.pick(palette)
	local y = 0
	local segment = 0
	while y < height do
		local len = rng.range(3, 4.5)
		local sway = if segment % 2 == 0 then 0.25 else -0.25
		piece(model, "KelpStalk", Vector3.new(0.8, len, 0.8), base * CFrame.new(sway, y + len / 2, 0), colour)
		if segment % 2 == 1 then
			local side = if segment % 4 == 1 then 1 else -1
			piece(model, "KelpLeaf", Vector3.new(1.6, 0.4, 0.7), base * CFrame.new(sway + side * 1, y + len * 0.7, 0), colour)
		end
		y += len
		segment += 1
	end
	return model
end

local function rocks(parent: Instance, rng, base: CFrame, size: number, colour: Color3)
	local model = Util.model("Rocks", parent)
	for k = 1, rng.int(2, 4) do
		local w = size * rng.range(0.5, 1)
		local h = size * rng.range(0.35, 0.8)
		local d = size * rng.range(0.5, 1)
		local offset = if k == 1 then CFrame.new(0, 0, 0) else CFrame.new(rng.range(-0.6, 0.6) * size, 0, rng.range(-0.6, 0.6) * size)
		piece(model, "Rock", Vector3.new(w, h, d), base * offset * yaw(rng) * CFrame.new(0, h / 2 - 0.4, 0), colour, true)
	end
	return model
end

local function shell(parent: Instance, rng, base: CFrame, palette)
	local model = Util.model("Shell", parent)
	local colour = rng.pick(palette)
	local b = base * yaw(rng)
	piece(model, "Shell", Vector3.new(1.2, 0.4, 1), b * CFrame.new(0, 0.2, 0), colour)
	piece(model, "Shell", Vector3.new(0.8, 0.3, 0.7), b * CFrame.new(0, 0.55, 0.05), colour)
	return model
end

local function pinnacle(parent: Instance, rng, base: CFrame, colour: Color3)
	local model = Util.model("RockPinnacle", parent)
	local w = rng.range(10, 14)
	local y = -2
	for _ = 1, rng.int(3, 5) do
		local h = rng.range(6, 12)
		piece(model, "Rock", Vector3.new(w, h, w * rng.range(0.8, 1.1)), base * yaw(rng) * CFrame.new(0, y + h / 2, 0), colour, true)
		y += h - 0.5
		w *= rng.range(0.62, 0.78)
	end
	return model
end

-- Rock arch deep enough to read as a short swim-through cave.
local function rockArch(parent: Instance, rng, base: CFrame, colour: Color3)
	local model = Util.model("RockArch", parent)
	local gap = rng.range(12, 16)
	local legW = rng.range(6, 9)
	local depth = rng.range(10, 18)
	local height = rng.range(14, 20)
	for _, side in { -1, 1 } do
		piece(model, "Rock", Vector3.new(legW, height + 2, depth), base * CFrame.new(side * (gap / 2 + legW / 2), height / 2 - 1, 0), colour, true)
	end
	local roof = rng.range(5, 8)
	piece(model, "Rock", Vector3.new(gap + legW * 2 + 2, roof, depth + 2), base * CFrame.new(0, height + roof / 2 - 0.5, 0), colour, true)
	piece(model, "Rock", Vector3.new(gap + legW, roof * 0.6, depth * 0.7), base * CFrame.new(rng.range(-2, 2), height + roof + roof * 0.3 - 1, 0), colour, true)
	return model
end

local function spire(parent: Instance, rng, base: CFrame, colour: Color3)
	local model = Util.model("AbyssSpire", parent)
	local w = rng.range(24, 40)
	local y = -4
	for _ = 1, rng.int(3, 5) do
		local h = rng.range(30, 70)
		piece(model, "Rock", Vector3.new(w, h, w), base * yaw(rng) * CFrame.new(0, y + h / 2, 0), colour, true)
		y += h - 2
		w *= rng.range(0.6, 0.8)
	end
	return model
end

function DecorBuilder.build(parent: Instance, Config, shape, ground)
	local H, S, P = Config.Hub, Config.Seabed, Config.Palette
	local decor = Util.folder("Decor", parent)
	local rng = Util.newRng(Config.SEED + 23)
	local platform = H.PLATFORM_RADIUS

	-- Keep a clear corridor in front of every gate out to the gentle slope.
	local function inGateCorridor(angle: number, radius: number): boolean
		if radius > platform + S.GENTLE_END then
			return false
		end
		for _, gateAngle in H.GATE_ANGLES do
			if math.rad(Util.angleDelta(angle, gateAngle)) * radius < 16 then
				return true
			end
		end
		return false
	end

	-- Scatter `count` items between two radii. `place` gets a ground frame and the depth.
	local function scatter(folder: Instance, count: number, fromR: number, toR: number, maxSlope: number, place)
		local placed, attempts = 0, 0
		while placed < count and attempts < count * 12 do
			attempts += 1
			local angle = rng.range(0, 360)
			local radius = math.sqrt(rng.range(fromR * fromR, toR * toR))
			local pos = Util.polar(angle, radius, 0)
			if not inGateCorridor(angle, radius) and ground.isOpen(pos.X, pos.Z) and ground.slopeAt(pos.X, pos.Z) <= maxSlope then
				local y = ground.heightAt(pos.X, pos.Z)
				place(CFrame.new(pos.X, y, pos.Z), y, angle, radius)
				placed += 1
			end
		end
	end

	local rockAt = function(y: number)
		return Util.ramp(Config.RockRamp, y)
	end

	-- Rich ring hugging the platform base.
	local ring = Util.folder("PlatformRing", decor)
	local ringFrom, ringTo = H.SKIRT.INNER + 5, platform + 16
	scatter(ring, 64, ringFrom, ringTo, 99, function(base)
		coral(ring, rng, base, P.Coral, rng.range(1, 1.5))
	end)
	scatter(ring, 34, ringFrom + 2, ringTo, 99, function(base)
		kelp(ring, rng, base, rng.range(9, 18), P.Kelp)
	end)
	scatter(ring, 24, platform, ringTo, 99, function(base, y)
		rocks(ring, rng, base, rng.range(2.5, 5), rockAt(y))
	end)
	scatter(ring, 22, ringFrom, ringTo, 99, function(base)
		shell(ring, rng, base, P.Shell)
	end)

	-- Starter seabed: beginner coral, kelp and small rocks, easy to swim over.
	local shallow = Util.folder("ShallowShelf", decor)
	local flatFrom, flatTo = platform + 16, platform + S.FLAT_END
	scatter(shallow, 36, flatFrom, flatTo, 2, function(base)
		coral(shallow, rng, base, P.Coral, rng.range(0.9, 1.3))
	end)
	scatter(shallow, 30, flatFrom, flatTo, 2, function(base)
		kelp(shallow, rng, base, rng.range(8, 16), P.Kelp)
	end)
	scatter(shallow, 30, flatFrom, flatTo, 2, function(base, y)
		rocks(shallow, rng, base, rng.range(2, 4), rockAt(y))
	end)
	scatter(shallow, 12, flatFrom, flatTo, 2, function(base)
		shell(shallow, rng, base, P.Shell)
	end)

	-- Gentle slope: larger rocks, more kelp.
	local gentle = Util.folder("GentleSlope", decor)
	local gentleFrom, gentleTo = platform + S.FLAT_END, platform + S.GENTLE_END
	scatter(gentle, 28, gentleFrom, gentleTo, 4, function(base, y)
		rocks(gentle, rng, base, rng.range(5, 10), rockAt(y))
	end)
	scatter(gentle, 24, gentleFrom, gentleTo, 2, function(base)
		coral(gentle, rng, base, P.Coral, rng.range(1, 1.6))
	end)
	scatter(gentle, 24, gentleFrom, gentleTo, 2, function(base)
		kelp(gentle, rng, base, rng.range(12, 24), P.Kelp)
	end)

	-- Broken shelves: rock formations and swim-through arches.
	local shelves = Util.folder("BrokenShelves", decor)
	local shelfFrom, shelfTo = platform + S.GENTLE_END, platform + S.STEEP_END
	scatter(shelves, 5, shelfFrom + 10, shelfTo - 10, 4, function(base, y, angle)
		-- Arches face along the slope so the opening frames the deeper water.
		rockArch(shelves, rng, CFrame.new(base.Position) * CFrame.Angles(0, math.rad(-angle), 0), rockAt(y))
	end)
	scatter(shelves, 12, shelfFrom, shelfTo, 4, function(base, y)
		pinnacle(shelves, rng, base, rockAt(y))
	end)
	scatter(shelves, 16, shelfFrom, shelfTo, 4, function(base, y)
		rocks(shelves, rng, base, rng.range(6, 12), rockAt(y))
	end)
	scatter(shelves, 14, shelfFrom, shelfTo, 2, function(base)
		coral(shelves, rng, base, P.Coral, rng.range(1.2, 1.8))
	end)
	scatter(shelves, 12, shelfFrom, shelfTo, 2, function(base)
		kelp(shelves, rng, base, rng.range(14, 26), P.Kelp)
	end)

	-- Cliff approach: coral gathers along the upper edge of the drop.
	local approach = Util.folder("CliffApproach", decor)
	local approachFrom = platform + S.STEEP_END
	local lipMax = platform + S.LIP_BASE + S.LIP_FRONT_BIAS + S.LIP_NOISE * 2
	local function nearLip(angle: number, radius: number): boolean
		local lip = platform + shape:lipDistance(angle)
		return radius < lip - 4 and radius > lip - 36
	end
	for _, spec in { { count = 40, kind = "coral" }, { count = 12, kind = "sponge" }, { count = 12, kind = "rocks" } } do
		local placed, attempts = 0, 0
		while placed < spec.count and attempts < spec.count * 20 do
			attempts += 1
			local angle = rng.range(0, 360)
			local radius = rng.range(approachFrom, lipMax)
			local pos = Util.polar(angle, radius, 0)
			if nearLip(angle, radius) and ground.isOpen(pos.X, pos.Z) and ground.slopeAt(pos.X, pos.Z) <= 4 then
				local y = ground.heightAt(pos.X, pos.Z)
				local base = CFrame.new(pos.X, y, pos.Z)
				if spec.kind == "coral" then
					coral(approach, rng, base, P.Coral, rng.range(1.2, 2))
				elseif spec.kind == "sponge" then
					sponge(approach, rng, base * yaw(rng), rng.pick(P.Coral), rng.range(1.4, 2.2))
				else
					rocks(approach, rng, base, rng.range(5, 9), rockAt(y))
				end
				placed += 1
			end
		end
	end

	-- Great cliff: only the first ledge carries a little life; deeper stays bare.
	local cliff = Util.folder("GreatCliff", decor)
	local placed, attempts = 0, 0
	while placed < 14 and attempts < 600 do
		attempts += 1
		local angle = rng.range(0, 360)
		local lip = platform + shape:lipDistance(angle)
		local radius = lip + rng.range(3, 12)
		local pos = Util.polar(angle, radius, 0)
		local y = ground.heightAt(pos.X, pos.Z)
		if ground.isOpen(pos.X, pos.Z) and math.abs(y - S.TERRACES[1]) < 10 and ground.slopeAt(pos.X, pos.Z) <= 6 then
			sponge(cliff, rng, CFrame.new(pos.X, y, pos.Z), rng.pick(P.Coral):Lerp(Config.RockRamp[4].color, 0.35), rng.range(1.2, 2))
			placed += 1
		end
	end

	-- Abyss spires: silhouettes seen from the cliff edge.
	local abyss = Util.folder("Abyss", decor)
	for k = 0, 13 do
		local angle = k * 360 / 14 + rng.range(-10, 10)
		local radius = rng.range(600, 940)
		local pos = Util.polar(angle, radius, 0)
		spire(abyss, rng, CFrame.new(pos.X, S.ABYSS_Y, pos.Z), rockAt(S.ABYSS_Y))
	end

	return decor
end

return DecorBuilder
