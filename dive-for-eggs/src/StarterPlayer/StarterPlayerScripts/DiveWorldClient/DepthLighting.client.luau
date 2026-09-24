-- Blends lighting, haze and water colour with the camera's depth below the hub floor:
-- bright cyan around the hub, deeper blue down the slope, dark navy (never black) below
-- the great cliff. Values come from Config.DepthLighting.

local Lighting = game:GetService("Lighting")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage:WaitForChild("DiveWorld"):WaitForChild("Config"))

local SMOOTHING = 3 -- per second
local APPLY_STEP = 0.5 -- studs of depth change before properties are touched again

local terrain = workspace.Terrain
local smoothedDepth = nil
local appliedDepth = math.huge

local function apply(depth: number)
	local look = Config.sampleDepthLighting(depth)
	Lighting.Ambient = look.ambient
	Lighting.OutdoorAmbient = look.outdoorAmbient
	Lighting.Brightness = look.brightness
	Lighting.ExposureCompensation = look.exposure
	terrain.WaterColor = look.waterColor
	terrain.WaterTransparency = look.waterTransparency

	local atmosphere = Lighting:FindFirstChildOfClass("Atmosphere")
	if atmosphere then
		atmosphere.Density = look.atmosphereDensity
		atmosphere.Color = look.atmosphereColor
		atmosphere.Decay = look.atmosphereDecay
		atmosphere.Haze = look.atmosphereHaze
	end
	local grade = Lighting:FindFirstChild("DiveColorCorrection")
	if grade and grade:IsA("ColorCorrectionEffect") then
		grade.TintColor = look.tint
		grade.Saturation = look.saturation
		grade.Contrast = look.contrast
	end
end

RunService.RenderStepped:Connect(function(dt)
	local camera = workspace.CurrentCamera
	if not camera then
		return
	end
	local depth = math.max(0, Config.Hub.FLOOR_Y - camera.CFrame.Position.Y)
	if smoothedDepth == nil then
		smoothedDepth = depth
	else
		smoothedDepth += (depth - smoothedDepth) * (1 - math.exp(-SMOOTHING * dt))
	end
	if math.abs(smoothedDepth - appliedDepth) >= APPLY_STEP then
		appliedDepth = smoothedDepth
		apply(smoothedDepth)
	end
end)
