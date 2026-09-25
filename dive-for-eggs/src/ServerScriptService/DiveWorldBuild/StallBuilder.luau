-- Generic central market stall, modelled on the reference stall turnaround with all
-- product/branding content removed: four chunky posts, top beams, sloped striped canopy,
-- a thick counter that wraps the front, sides and back, and two rows of lower rails.
-- One master is built, stored in ServerStorage, and cloned for the four coloured stalls;
-- only the canopy colour differs between them.

local ServerStorage = game:GetService("ServerStorage")

local Util = require(script.Parent.Util)

local StallBuilder = {}

local TEMPLATE_FOLDER = "DiveWorldTemplates"
local MASTER_NAME = "CentralStall_Master"

local function wood(parent: Instance, name: string, size: Vector3, cframe: CFrame, colour: Color3)
	return Util.part({
		name = name,
		size = size,
		cframe = cframe,
		color = colour,
		parent = parent,
	})
end

-- Builds the master stall around the origin: floor at y = 0, front (counter side) at -Z.
function StallBuilder.buildMaster(Config): Model
	local S, P = Config.StallShape, Config.Palette
	local stall = Instance.new("Model")
	stall.Name = MASTER_NAME

	local frame = Util.model("Frame", stall)
	local roof = Util.model("Roof", stall)
	local counter = Util.model("Counter", stall)
	local lower = Util.model("LowerSupports", stall)

	local halfW, halfD, post = S.BODY_WIDTH / 2, S.BODY_DEPTH / 2, S.POST
	local postX, postZ = halfW - post / 2, halfD - post / 2
	local slope = math.rad(S.ROOF_SLOPE_DEG)
	local rise = math.tan(slope)
	-- Height of the roof underside at depth z (front lower, rising toward the back).
	local function roofUnderside(z: number): number
		return S.POST_HEIGHT + rise * (z + halfD)
	end

	-- Posts reach a little into the roof so the joint never shows a gap.
	for _, x in { -postX, postX } do
		for _, z in { -postZ, postZ } do
			local top = roofUnderside(z + (if z < 0 then -post / 2 else post / 2)) + 0.3
			wood(frame, "Post", Vector3.new(post, top, post), CFrame.new(x, top / 2, z), P.WoodMain)
		end
	end

	-- Top beams: front and back across, sides sloped with the roof.
	local beamDepth = post * 0.8
	for _, z in { -postZ, postZ } do
		local y = roofUnderside(z) - S.TOP_BEAM / 2
		wood(frame, "TopBeam", Vector3.new(S.BODY_WIDTH, S.TOP_BEAM, beamDepth), CFrame.new(0, y, z), P.WoodDark)
	end
	for _, x in { -postX, postX } do
		local y = roofUnderside(0) - S.TOP_BEAM / 2
		wood(
			frame,
			"TopBeam",
			Vector3.new(beamDepth, S.TOP_BEAM, S.BODY_DEPTH),
			CFrame.new(x, y, 0) * CFrame.Angles(-slope, 0, 0),
			P.WoodDark
		)
	end

	-- Canopy: alternating stripes running front to back, the roof's only colour.
	local roofFront, roofBack = -(halfD + S.ROOF_FRONT_OVERHANG), halfD + S.ROOF_BACK_OVERHANG
	local roofDepth = (roofBack - roofFront) / math.cos(slope)
	local roofMidZ = (roofFront + roofBack) / 2
	local roofFrame = CFrame.new(0, roofUnderside(roofMidZ) + S.ROOF_THICKNESS / 2, roofMidZ)
		* CFrame.Angles(-slope, 0, 0)
	local stripe = S.ROOF_WIDTH / S.ROOF_STRIPES
	for i = 1, S.ROOF_STRIPES do
		local coloured = i % 2 == 1
		local part = Util.part({
			name = "CanopyStripe",
			size = Vector3.new(stripe + 0.01, S.ROOF_THICKNESS, roofDepth),
			cframe = roofFrame * CFrame.new(-S.ROOF_WIDTH / 2 + (i - 0.5) * stripe, 0, 0),
			color = if coloured then P.Canopy.Blue else P.CanopyWhite,
			parent = roof,
		})
		part:SetAttribute("CanopyStripe", if coloured then "Color" else "White")
	end

	-- Counter: thick front slab sticking out past the posts, side returns, back shelf.
	local counterY = S.COUNTER_TOP - S.COUNTER_THICKNESS / 2
	local counterWidth = S.BODY_WIDTH + 2 * S.COUNTER_SIDE_OVERHANG
	local frontFace = -(halfD + S.COUNTER_FRONT_REACH)
	local frontBack = frontFace + S.COUNTER_FRONT_DEPTH
	local backFace = halfD + 0.2
	wood(
		counter,
		"CounterFront",
		Vector3.new(counterWidth, S.COUNTER_THICKNESS, S.COUNTER_FRONT_DEPTH),
		CFrame.new(0, counterY, frontFace + S.COUNTER_FRONT_DEPTH / 2),
		P.WoodLight
	)
	for _, side in { -1, 1 } do
		wood(
			counter,
			"CounterSide",
			Vector3.new(S.COUNTER_RIM, S.COUNTER_THICKNESS, backFace - frontBack),
			CFrame.new(side * (counterWidth / 2 - S.COUNTER_RIM / 2), counterY, (frontBack + backFace) / 2),
			P.WoodLight
		)
		-- Chunky bracket under the counter's front overhang, against each front post.
		wood(
			counter,
			"CounterBracket",
			Vector3.new(post * 0.7, 0.9, S.COUNTER_FRONT_REACH + 0.1),
			CFrame.new(
				side * postX,
				S.COUNTER_TOP - S.COUNTER_THICKNESS - 0.45,
				-(halfD + S.COUNTER_FRONT_REACH / 2) + 0.05
			),
			P.WoodDark
		)
	end
	wood(
		counter,
		"CounterBack",
		Vector3.new(counterWidth - 2 * S.COUNTER_RIM, S.COUNTER_THICKNESS, S.COUNTER_RIM),
		CFrame.new(0, counterY, backFace - S.COUNTER_RIM / 2),
		P.WoodLight
	)

	-- Lower rails on all four sides, between the posts.
	local spanX, spanZ = S.BODY_WIDTH - 2 * post, S.BODY_DEPTH - 2 * post
	for _, y in S.RAIL_HEIGHTS do
		for _, z in { -postZ, postZ } do
			wood(lower, "Rail", Vector3.new(spanX, S.RAIL, S.RAIL), CFrame.new(0, y, z), P.WoodMain)
		end
		for _, x in { -postX, postX } do
			wood(lower, "Rail", Vector3.new(S.RAIL, S.RAIL, spanZ), CFrame.new(x, y, 0), P.WoodMain)
		end
	end

	stall.WorldPivot = CFrame.new()
	return stall
end

function StallBuilder.paint(stall: Model, Config, colourName: string)
	local colour = Config.Palette.Canopy[colourName]
	for _, part in stall:GetDescendants() do
		if part:IsA("BasePart") and part:GetAttribute("CanopyStripe") == "Color" then
			part.Color = colour
		end
	end
	stall:SetAttribute("StallColor", colourName)
end

-- Stores a fresh master in ServerStorage so later passes can clone or edit it.
function StallBuilder.installTemplate(Config): Model
	local folder = ServerStorage:FindFirstChild(TEMPLATE_FOLDER)
	if not folder then
		folder = Util.folder(TEMPLATE_FOLDER, ServerStorage)
	end
	local existing = folder:FindFirstChild(MASTER_NAME)
	if existing then
		existing:Destroy()
	end
	local master = StallBuilder.buildMaster(Config)
	master.Parent = folder
	return master
end

-- Places the four coloured stalls around `centre`, each front facing the centre.
function StallBuilder.build(parent: Instance, Config, centre: Vector3): Folder
	local existing = parent:FindFirstChild("CentralStalls")
	if existing then
		existing:Destroy()
	end
	local folder = Util.folder("CentralStalls", parent)
	local master = StallBuilder.installTemplate(Config)
	local St = Config.Stalls
	for i, angle in St.ANGLES do
		local colourName = St.COLORS[i]
		local stall = master:Clone()
		stall.Name = "CentralStall_" .. colourName
		StallBuilder.paint(stall, Config, colourName)
		local pos = centre + Util.dir(angle) * St.RADIUS
		stall:PivotTo(CFrame.lookAt(pos, Vector3.new(centre.X, pos.Y, centre.Z)))
		stall:SetAttribute("Angle", angle)
		stall.Parent = folder
	end
	return folder
end

-- Distance from the plaza centre to the front of the stall counters.
function StallBuilder.frontRadius(Config): number
	local S = Config.StallShape
	return Config.Stalls.RADIUS - (S.BODY_DEPTH / 2 + S.COUNTER_FRONT_REACH)
end

-- Largest radius the statue (including fins and coral) may use.
function StallBuilder.statueRadius(Config): number
	return StallBuilder.frontRadius(Config) - Config.Statue.WALK_RING
end

return StallBuilder
