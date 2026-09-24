-- Bright, pastel underwater lighting in the Dive Down family: readable, blue haze
-- instead of black distance, soft shadows. DepthLighting on the client darkens it with depth.

local Lighting = game:GetService("Lighting")

local LightingBuilder = {}

local function replace(className: string, name: string): Instance
	local existing = Lighting:FindFirstChild(name)
	if existing then
		existing:Destroy()
	end
	local effect = Instance.new(className)
	effect.Name = name
	return effect
end

function LightingBuilder.build(Config)
	local look = Config.sampleDepthLighting(0)

	Lighting.ClockTime = 12.5
	Lighting.GeographicLatitude = 20
	Lighting.Brightness = look.brightness
	Lighting.Ambient = look.ambient
	Lighting.OutdoorAmbient = look.outdoorAmbient
	Lighting.ColorShift_Top = Color3.fromRGB(170, 230, 255)
	Lighting.ColorShift_Bottom = Color3.fromRGB(40, 90, 140)
	Lighting.EnvironmentDiffuseScale = 0.6
	Lighting.EnvironmentSpecularScale = 0.2
	Lighting.GlobalShadows = true
	Lighting.ShadowSoftness = 0.6
	Lighting.ExposureCompensation = look.exposure

	-- Only one Atmosphere can be active.
	for _, child in Lighting:GetChildren() do
		if child:IsA("Atmosphere") then
			child:Destroy()
		end
	end
	local atmosphere = replace("Atmosphere", "DiveAtmosphere") :: Atmosphere
	atmosphere.Density = look.atmosphereDensity
	atmosphere.Offset = 0.05
	atmosphere.Color = look.atmosphereColor
	atmosphere.Decay = look.atmosphereDecay
	atmosphere.Glare = 0
	atmosphere.Haze = look.atmosphereHaze
	atmosphere.Parent = Lighting

	local grade = replace("ColorCorrectionEffect", "DiveColorCorrection") :: ColorCorrectionEffect
	grade.TintColor = look.tint
	grade.Saturation = look.saturation
	grade.Contrast = look.contrast
	grade.Brightness = 0.03
	grade.Parent = Lighting

	local bloom = replace("BloomEffect", "DiveBloom") :: BloomEffect
	bloom.Intensity = 0.35
	bloom.Size = 28
	bloom.Threshold = 1.4
	bloom.Parent = Lighting
end

return LightingBuilder
