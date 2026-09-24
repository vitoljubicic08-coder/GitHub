-- Shared numbers for the Dive for Eggs starter world.
-- The server builders, the client effects and the offline preview all read this module,
-- so layout, palette and depth lighting can only be tuned in one place.

local Config = {}

Config.WORLD_FOLDER_NAME = "DiveStarterWorld"
Config.SEED = 20260924

-- Angles are degrees clockwise from north (-Z) when looking down from above.
-- North = back gate, south (+Z) = front gate / spawn side, east = +X.
Config.Hub = {
	FLOOR_Y = 0, -- top of the walkable floor
	FLOOR_THICKNESS = 4,

	PLAZA_RADIUS = 26, -- 52 stud diameter open plaza
	PLAZA_RING_WIDTH = 1.4,

	PLOT_COUNT = 6,
	-- Plot axes sit at 30, 90, 150, 210, 270, 330 so the north and south gates land on
	-- sector dividers (open avenues) and the east/west gates sit behind plots 2 and 5,
	-- matching the concept image.
	PLOT_FIRST_ANGLE = 30,

	PAD_WIDTH = 48, -- along the circumference (future viewing glass side)
	PAD_DEPTH = 32, -- radial
	PAD_INNER_RADIUS = 64, -- front edge of the pad, measured from hub centre
	PAD_FRAME = 1.5,
	PAD_FRAME_HEIGHT = 0.6,
	PAD_SURFACE_HEIGHT = 0.45,
	PAD_GREEN_MARGIN = 3,

	DIVIDER_WIDTH = 0.8,
	OUTER_RING_RADIUS = 114,
	INNER_GREEN = { INNER = 30, OUTER = 37, HALF_SPAN = 18 },
	BACK_GREEN = { INNER = 104, OUTER = 110, HALF_SPAN = 20, GATE_GAP = 8 },

	WALL_INNER_RADIUS = 126,
	WALL_THICKNESS = 6,
	WALL_HEIGHT = 6,
	WALL_SEGMENT_DEG = 5,
	PILLAR_EVERY_DEG = 30,

	GATE_ANGLES = { 0, 90, 180, 270 },
	GATE_NAMES = { "North", "East", "South", "West" },
	GATE_OPENING_WIDTH = 14,
	GATE_SPRING_HEIGHT = 11, -- the arch springs from here; crown = spring + width / 2
	GATE_TOWER_WIDTH = 8,
	GATE_TOWER_HEIGHT = 24,
	GATE_DEPTH = 16,

	SKIRT = { INNER = 131, OUTER = 139, TOP = -2 },
	BASE = { INNER = 138, OUTER = 146, TOP = -4 },
	PLATFORM_RADIUS = 146, -- outer edge of the stone base; terrain distances start here

	SPAWN_ANGLE = 180, -- just inside the front (south) gate
	SPAWN_RADIUS = 100, -- on the south avenue, facing the plaza
}

Config.Bubble = {
	RADIUS = 134, -- horizontal radius at floor level; the gate water curtains sit on this line
	HEIGHT = 150, -- vertical semi-axis, a little taller than a hemisphere
	MEMBRANE_RADIUS = 133.5,
	TRANSPARENCY = 0.88,
	REFLECTANCE = 0.2,
}

Config.Ocean = {
	SURFACE_Y = 220,
	BOTTOM_Y = -496, -- stays above Roblox's default FallenPartsDestroyHeight (-500)
	HALF_EXTENT = 1152, -- water fill covers +-this on X and Z
	CHUNK = 384,
}

Config.Seabed = {
	SEABED_Y = -6, -- flat starter seabed next to the platform
	CELL = 8,
	FINE_HALF_EXTENT = 576,
	COARSE_CELL = 64,

	-- Distances are measured outward from Hub.PLATFORM_RADIUS.
	FLAT_END = 40,
	GENTLE_END = 100,
	STEEP_END = 180,

	LIP_BASE = 245, -- average distance to the deep-ocean cliff lip
	LIP_FRONT_BIAS = 25, -- lip is closer on the south (spawn gate) side
	LIP_NOISE = 22,
	CRACK_COUNT = 7,

	TERRACES = { -165, -235, -310, -390 }, -- ledge heights stepping down the great cliff
	SCREE_WIDTH = 32,
	ABYSS_Y = -470,

	CAVE_ANGLES = { 22, 97, 163, 214, 301 },
	OVERHANG_ANGLES = { 8, 58, 128, 188, 246, 276, 332 },

	MASSIF_RADIUS = 1040, -- stepped basin rim that closes the world, far out in the haze
}

local rgb = Color3.fromRGB

Config.Palette = {
	Floor = rgb(238, 228, 200),
	FloorLight = rgb(247, 241, 224),
	Green = rgb(98, 204, 84),
	Trim = rgb(96, 122, 168),
	PadFrame = rgb(66, 86, 132),
	PadSurface = rgb(176, 181, 214),
	PadFront = rgb(88, 206, 236),

	Wall = rgb(72, 94, 138),
	WallCap = rgb(112, 132, 176),
	Tower = rgb(80, 102, 148),
	TowerCap = rgb(122, 142, 186),
	Threshold = rgb(150, 166, 196),
	Skirt = rgb(62, 82, 122),
	Base = rgb(54, 72, 110),

	LanternFrame = rgb(46, 52, 70),
	LanternGlow = rgb(255, 184, 96),
	LanternLight = rgb(255, 190, 120),
	Banner = rgb(32, 54, 118),
	BannerEmblem = rgb(236, 244, 255),

	WaterCurtain = rgb(96, 214, 250),
	WaterStreak = rgb(206, 246, 255),
	Foam = rgb(236, 252, 255),
	Bubble = rgb(176, 236, 255),

	Kelp = { rgb(64, 172, 84), rgb(44, 146, 72), rgb(96, 192, 92) },
	Coral = {
		rgb(255, 108, 182),
		rgb(255, 152, 64),
		rgb(172, 92, 232),
		rgb(84, 204, 232),
		rgb(255, 216, 72),
		rgb(232, 72, 204),
		rgb(255, 98, 98),
	},
	Shell = { rgb(255, 196, 206), rgb(250, 240, 226) },
}

-- Colour ramps by world height. Blended continuously so there is never a hard colour line.
Config.SandRamp = {
	{ y = -6, color = rgb(225, 215, 180) },
	{ y = -40, color = rgb(206, 202, 176) },
	{ y = -100, color = rgb(164, 174, 172) },
	{ y = -200, color = rgb(112, 128, 148) },
	{ y = -470, color = rgb(58, 74, 102) },
}

Config.RockRamp = {
	{ y = -6, color = rgb(75, 105, 140) },
	{ y = -60, color = rgb(60, 90, 128) },
	{ y = -115, color = rgb(45, 75, 115) },
	{ y = -260, color = rgb(36, 63, 100) },
	{ y = -470, color = rgb(28, 50, 84) },
}

-- Lighting by depth below the hub floor. The hub stays bright; the far side of the
-- great cliff reads deep blue, never black.
Config.DepthLighting = {
	{
		depth = 0,
		ambient = rgb(150, 180, 210),
		outdoorAmbient = rgb(160, 200, 230),
		brightness = 3,
		exposure = 0.25,
		atmosphereDensity = 0.3,
		atmosphereColor = rgb(120, 210, 245),
		atmosphereDecay = rgb(60, 140, 210),
		atmosphereHaze = 1,
		tint = rgb(230, 248, 255),
		saturation = 0.15,
		contrast = 0.05,
		waterColor = rgb(40, 170, 215),
		waterTransparency = 1,
	},
	{
		depth = 60,
		ambient = rgb(130, 165, 200),
		outdoorAmbient = rgb(140, 185, 220),
		brightness = 2.8,
		exposure = 0.2,
		atmosphereDensity = 0.34,
		atmosphereColor = rgb(95, 190, 235),
		atmosphereDecay = rgb(45, 120, 195),
		atmosphereHaze = 1.3,
		tint = rgb(215, 240, 255),
		saturation = 0.12,
		contrast = 0.06,
		waterColor = rgb(35, 150, 205),
		waterTransparency = 0.95,
	},
	{
		depth = 130,
		ambient = rgb(105, 140, 185),
		outdoorAmbient = rgb(115, 160, 205),
		brightness = 2.5,
		exposure = 0.1,
		atmosphereDensity = 0.4,
		atmosphereColor = rgb(70, 160, 220),
		atmosphereDecay = rgb(35, 95, 175),
		atmosphereHaze = 1.6,
		tint = rgb(195, 225, 255),
		saturation = 0.06,
		contrast = 0.08,
		waterColor = rgb(28, 120, 190),
		waterTransparency = 0.85,
	},
	{
		depth = 260,
		ambient = rgb(70, 100, 150),
		outdoorAmbient = rgb(80, 120, 175),
		brightness = 2.1,
		exposure = 0,
		atmosphereDensity = 0.48,
		atmosphereColor = rgb(45, 120, 195),
		atmosphereDecay = rgb(25, 70, 145),
		atmosphereHaze = 2,
		tint = rgb(170, 205, 250),
		saturation = 0,
		contrast = 0.1,
		waterColor = rgb(20, 90, 160),
		waterTransparency = 0.7,
	},
	{
		depth = 470,
		ambient = rgb(40, 62, 100),
		outdoorAmbient = rgb(48, 75, 120),
		brightness = 1.6,
		exposure = -0.1,
		atmosphereDensity = 0.58,
		atmosphereColor = rgb(25, 70, 140),
		atmosphereDecay = rgb(15, 40, 95),
		atmosphereHaze = 2.4,
		tint = rgb(140, 175, 235),
		saturation = -0.08,
		contrast = 0.12,
		waterColor = rgb(12, 55, 115),
		waterTransparency = 0.5,
	},
}

-- Returns the blended lighting values for a depth (studs below the hub floor).
function Config.sampleDepthLighting(depth: number): { [string]: any }
	local frames = Config.DepthLighting
	if depth <= frames[1].depth then
		return frames[1]
	end
	for i = 2, #frames do
		local a, b = frames[i - 1], frames[i]
		if depth <= b.depth then
			local t = (depth - a.depth) / (b.depth - a.depth)
			local blended = {}
			for key, value in a do
				local other = b[key]
				if type(value) == "number" then
					blended[key] = value + (other - value) * t
				else
					blended[key] = value:Lerp(other, t)
				end
			end
			return blended
		end
	end
	return frames[#frames]
end

return Config
