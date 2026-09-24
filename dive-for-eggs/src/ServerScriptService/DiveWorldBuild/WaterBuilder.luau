-- Fills the basin with terrain water and carves the dry air pocket under the bubble.
-- Terrain water gives real swimming; crossing a gate curtain moves a player straight
-- from the dry hub into the water with no teleport.

local WaterBuilder = {}

local VOXEL = 4

local function alignDown(value: number): number
	return math.floor(value / VOXEL) * VOXEL
end

function WaterBuilder.build(Config)
	local terrain = workspace.Terrain
	local O, B = Config.Ocean, Config.Bubble
	local F = Config.Hub.FLOOR_Y
	local look = Config.sampleDepthLighting(0)

	terrain.WaterColor = look.waterColor
	terrain.WaterTransparency = look.waterTransparency
	terrain.WaterReflectance = 0
	terrain.WaterWaveSize = 0
	terrain.WaterWaveSpeed = 0

	-- Fill in voxel-aligned chunks; seams off the voxel grid leave faint water surfaces.
	local bottom, top = alignDown(O.BOTTOM_Y), alignDown(O.SURFACE_Y)
	local bands = math.ceil((top - bottom) / 400)
	local band = math.ceil((top - bottom) / bands / VOXEL) * VOXEL
	for x = -O.HALF_EXTENT, O.HALF_EXTENT - O.CHUNK, O.CHUNK do
		for z = -O.HALF_EXTENT, O.HALF_EXTENT - O.CHUNK, O.CHUNK do
			local y0 = bottom
			while y0 < top do
				local y1 = math.min(top, y0 + band)
				terrain:FillBlock(
					CFrame.new(x + O.CHUNK / 2, (y0 + y1) / 2, z + O.CHUNK / 2),
					Vector3.new(O.CHUNK, y1 - y0, O.CHUNK),
					Enum.Material.Water
				)
				y0 = y1
			end
		end
	end

	-- Air pocket with the same ellipsoid profile as the visible bubble.
	for y = alignDown(F - 8), F + B.HEIGHT, VOXEL do
		local h = y + VOXEL / 2 - F
		local radius = if h <= 0 then B.RADIUS else B.RADIUS * math.sqrt(math.max(0, 1 - (h / B.HEIGHT) ^ 2))
		if radius > VOXEL / 2 then
			terrain:FillCylinder(CFrame.new(0, y + VOXEL / 2, 0), VOXEL, radius, Enum.Material.Air)
		end
	end
end

return WaterBuilder
