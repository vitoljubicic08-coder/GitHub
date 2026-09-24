-- Height profile of the seabed around the hub.
-- The hub sits on a high shelf: level sand next to the platform, a gentle slope, broken
-- shelves, a long approach and finally a stepped deep-ocean cliff dropping to the abyss.
-- Pure maths only, so the builders, decor placement and tests all agree on the shape.

local Util = require(script.Parent.Util)

local SeabedShape = {}
SeabedShape.__index = SeabedShape

export type Zone = "Platform" | "ShallowShelf" | "GentleSlope" | "BrokenShelves" | "CliffApproach" | "GreatCliff" | "Abyss"

local function noise2(x: number, z: number, scale: number, salt: number): number
	-- math.noise sits mostly within +-0.5; stretch it to roughly +-1.
	return math.clamp(math.noise(x * scale + salt, z * scale - salt * 0.7, salt * 0.13) * 2, -1, 1)
end

function SeabedShape.new(Config)
	local self = setmetatable({}, SeabedShape)
	self.S = Config.Seabed
	self.platformRadius = Config.Hub.PLATFORM_RADIUS
	local rng = Util.newRng(Config.SEED + 7)
	self.cracks = {}
	for i = 1, self.S.CRACK_COUNT do
		table.insert(self.cracks, {
			angle = (i - 1) * 360 / self.S.CRACK_COUNT + rng.range(10, 40),
			depth = rng.range(16, 28),
			halfWidth = rng.range(5, 8),
		})
	end
	return self
end

-- Distance from the platform edge to the lip of the great cliff in a compass direction.
-- Closest on the south (front gate) side and irregular everywhere.
function SeabedShape:lipDistance(angleDeg: number): number
	local S = self.S
	local a = math.rad(angleDeg)
	local c, s = math.cos(a), math.sin(a)
	local wobble = math.noise(c * 1.3 + 5.31, s * 1.3 + 2.17, 0.61) * 2 + math.noise(c * 3.7 + 1.9, s * 3.7 + 8.3, 1.37) * 0.8
	return S.LIP_BASE + S.LIP_FRONT_BIAS * c + S.LIP_NOISE * wobble
end

-- Narrow cracks cut back into the lip, floored at the first ledge.
function SeabedShape:inCrack(angleDeg: number, d: number, lip: number): boolean
	local lipRadius = self.platformRadius + lip
	for _, crack in self.cracks do
		if d >= lip - crack.depth then
			local lateral = math.rad(Util.angleDelta(angleDeg, crack.angle)) * lipRadius
			if lateral < crack.halfWidth then
				return true
			end
		end
	end
	return false
end

function SeabedShape:heightAt(x: number, z: number): (number, Zone)
	local S = self.S
	local d = math.sqrt(x * x + z * z) - self.platformRadius
	if d < 0 then
		return S.SEABED_Y, "Platform"
	end

	local broad = noise2(x, z, 1 / 70, 3.7)
	local mid = noise2(x, z, 1 / 26, 9.1)
	local fine = noise2(x, z, 1 / 11, 5.3)

	if d < S.FLAT_END then
		-- Level sand; the odd one-stud bump appears only towards the outer edge.
		return S.SEABED_Y + Util.quantize(mid * 1.2 * d / S.FLAT_END, 1), "ShallowShelf"
	end
	if d < S.GENTLE_END then
		local t = (d - S.FLAT_END) / (S.GENTLE_END - S.FLAT_END)
		local y = S.SEABED_Y - 24 * Util.smoothstep(t) + broad * 5 * t + mid * 1.5
		return Util.quantize(y, 2), "GentleSlope"
	end
	if d < S.STEEP_END then
		local t = (d - S.GENTLE_END) / (S.STEEP_END - S.GENTLE_END)
		local y = -30 - 55 * t + broad * 10 * (0.5 + t) + mid * 2.5
		return Util.quantize(y, 4), "BrokenShelves"
	end

	local angle = Util.angleOf(x, z)
	local lip = self:lipDistance(angle)
	if d < lip and self:inCrack(angle, d, lip) then
		return Util.quantize(S.TERRACES[1] + broad * 8, 8), "GreatCliff"
	end
	if d < lip then
		local t = (d - S.STEEP_END) / math.max(1, lip - S.STEEP_END)
		local y = -85 - 30 * t + broad * 8 + mid * 2
		return Util.quantize(y, 4), "CliffApproach"
	end

	-- Stepped cliff: ragged terraces, a scree face, then the abyss floor. Widths and ledge
	-- heights drift slowly around the cliff so every ledge survives as one shelf.
	local T = S.TERRACES
	local e = d - lip
	local edge = 0
	local widthNoise = { mid, broad, mid, broad }
	for k, ledge in T do
		edge += 18 + 5 * (widthNoise[(k - 1) % #widthNoise + 1] + 1)
		if e < edge then
			return Util.quantize(ledge + broad * 8, 8), "GreatCliff"
		end
	end
	local scree = e - edge
	if scree < S.SCREE_WIDTH then
		local y = Util.lerp(T[#T] - 30, S.ABYSS_Y, Util.smoothstep(scree / S.SCREE_WIDTH)) + fine * 6
		return Util.quantize(y, 16), "GreatCliff"
	end
	return Util.quantize(S.ABYSS_Y + broad * 10, 16), "Abyss"
end

return SeabedShape
