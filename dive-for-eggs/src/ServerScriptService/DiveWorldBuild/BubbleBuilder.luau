-- The one enormous air bubble over the hub: a single smooth, almost invisible shell.
-- No ribs or panels. Its size matches the air pocket WaterBuilder carves in the ocean.

local Util = require(script.Parent.Util)

local BubbleBuilder = {}

function BubbleBuilder.build(parent: Instance, Config): Part
	local B = Config.Bubble
	local model = Util.model("Bubble", parent)
	local shell = Util.part({
		name = "AirBubble",
		size = Vector3.new(2 * B.RADIUS, 2 * B.HEIGHT, 2 * B.RADIUS),
		cframe = CFrame.new(0, Config.Hub.FLOOR_Y, 0),
		color = Config.Palette.Bubble,
		transparency = B.TRANSPARENCY,
		reflectance = B.REFLECTANCE,
		collide = false,
		shadow = false,
		parent = model,
	})
	-- A sphere mesh stretched to the part size gives a taller-than-hemisphere dome.
	-- Back faces are culled, so from inside the shell is invisible and the ocean is clear.
	local mesh = Instance.new("SpecialMesh")
	mesh.MeshType = Enum.MeshType.Sphere
	mesh.Parent = shell
	shell:SetAttribute("HorizontalRadius", B.RADIUS)
	shell:SetAttribute("Height", B.HEIGHT)
	return shell
end

return BubbleBuilder
