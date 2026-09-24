-- Builds the dry starter hub: solid studded floor, six-sector floor pattern, six aquarium
-- foundation pads, the retaining wall, four waterfall gates and the spawn.
-- The interior is deliberately empty apart from the floor, pads, walls and gates.

local Util = require(script.Parent.Util)

local HubBuilder = {}

-- Heights above the floor for flush floor details. Big enough to avoid z-fighting,
-- far too small to trip over.
local INLAY_TOP = 0.03
local TRIM_TOP = 0.06

local function sectorSpan(H): number
	return 360 / H.PLOT_COUNT
end

local function plotAngle(H, index: number): number
	return (H.PLOT_FIRST_ANGLE + (index - 1) * sectorSpan(H)) % 360
end

-- Splits [fromDeg, toDeg] around the given angles, leaving a gap of +-gap at each one.
local function splitAround(fromDeg: number, toDeg: number, angles: { number }, gap: number): { { number } }
	local ranges = { { fromDeg, toDeg } }
	for _, cut in angles do
		local nextRanges = {}
		for _, range in ranges do
			-- Bring the cut into the same turn as the range.
			local c = cut
			while c < range[1] - 180 do
				c += 360
			end
			while c > range[2] + 180 do
				c -= 360
			end
			local lo, hi = c - gap, c + gap
			if hi <= range[1] or lo >= range[2] then
				table.insert(nextRanges, range)
			else
				if lo > range[1] then
					table.insert(nextRanges, { range[1], lo })
				end
				if hi < range[2] then
					table.insert(nextRanges, { hi, range[2] })
				end
			end
		end
		ranges = nextRanges
	end
	return ranges
end

local function lantern(parent: Instance, base: CFrame, scale: number, P)
	local model = Util.model("Lantern", parent)
	local s = scale
	Util.part({
		name = "LanternBase",
		size = Vector3.new(3 * s, 0.6 * s, 3 * s),
		cframe = base * CFrame.new(0, 0.3 * s, 0),
		color = P.LanternFrame,
		parent = model,
	})
	local glow = Util.part({
		name = "LanternGlow",
		size = Vector3.new(2 * s, 2.2 * s, 2 * s),
		cframe = base * CFrame.new(0, 1.7 * s, 0),
		color = P.LanternGlow,
		material = Enum.Material.Neon,
		shadow = false,
		parent = model,
	})
	for _, sx in { -1, 1 } do
		for _, sz in { -1, 1 } do
			Util.part({
				name = "LanternPost",
				size = Vector3.new(0.45 * s, 2.2 * s, 0.45 * s),
				cframe = base * CFrame.new(sx * 1.15 * s, 1.7 * s, sz * 1.15 * s),
				color = P.LanternFrame,
				parent = model,
			})
		end
	end
	Util.part({
		name = "LanternRoof",
		size = Vector3.new(3.4 * s, 0.6 * s, 3.4 * s),
		cframe = base * CFrame.new(0, 3.1 * s, 0),
		color = P.LanternFrame,
		parent = model,
	})
	Util.part({
		name = "LanternCap",
		size = Vector3.new(1.6 * s, 0.5 * s, 1.6 * s),
		cframe = base * CFrame.new(0, 3.65 * s, 0),
		color = P.LanternFrame,
		parent = model,
	})
	local light = Instance.new("PointLight")
	light.Color = P.LanternLight
	light.Range = 18 * s
	light.Brightness = 1.4
	light.Shadows = false
	light.Parent = glow
	return model
end

local function buildFloor(hub: Instance, H, P)
	local folder = Util.folder("Floor", hub)
	local F = H.FLOOR_Y
	-- The stepped edge of the strip disc is tucked inside the retaining wall.
	local reach = H.WALL_INNER_RADIUS + H.WALL_THICKNESS / 2 - 1
	Util.disc(folder, "Floor", reach, 4, F - H.FLOOR_THICKNESS, F, P.Floor)

	-- Stone skirt and rough base that sink the platform into the seabed.
	local S, B = H.SKIRT, H.BASE
	Util.arc({
		name = "StoneSkirt",
		radius = (S.INNER + S.OUTER) / 2,
		width = S.OUTER - S.INNER,
		fromDeg = 0,
		toDeg = 360,
		bottomY = F - 9,
		topY = F + S.TOP,
		color = P.Skirt,
		stepDeg = 5,
		studs = "all",
		parent = folder,
	})
	local rng = Util.newRng(1103)
	local step = 5
	local outer = B.OUTER
	local length = 2 * outer * math.sin(math.rad(step / 2)) + 0.3
	for i = 0, 360 / step - 1 do
		local top = F + B.TOP + Util.quantize(rng.range(-1, 1), 0.5)
		local bottom = F - 12
		Util.part({
			name = "StoneBase",
			size = Vector3.new(length, top - bottom, B.OUTER - B.INNER),
			cframe = Util.radialFrame(step * (i + 0.5), (B.INNER + B.OUTER) / 2, (top + bottom) / 2),
			color = P.Base,
			studs = "all",
			parent = folder,
		})
	end
end

local function buildPattern(hub: Instance, H, P)
	local folder = Util.folder("FloorPattern", hub)
	local F = H.FLOOR_Y
	local span = sectorSpan(H)

	-- Central plaza: nothing but a double trim ring on the floor.
	Util.arc({
		name = "PlazaRing",
		radius = H.PLAZA_RADIUS,
		width = H.PLAZA_RING_WIDTH,
		fromDeg = 0,
		toDeg = 360,
		bottomY = F - 0.14,
		topY = F + TRIM_TOP,
		color = P.Trim,
		stepDeg = 5,
		decorative = true,
		parent = folder,
	})
	Util.arc({
		name = "PlazaInnerRing",
		radius = H.PLAZA_RADIUS - 2.6,
		width = 0.5,
		fromDeg = 0,
		toDeg = 360,
		bottomY = F - 0.14,
		topY = F + TRIM_TOP,
		color = P.Trim,
		stepDeg = 5,
		decorative = true,
		parent = folder,
	})

	-- Six thin radial dividers between the sectors, from the plaza ring to the wall.
	local r0 = H.PLAZA_RADIUS + H.PLAZA_RING_WIDTH / 2
	local r1 = H.WALL_INNER_RADIUS
	for k = 0, H.PLOT_COUNT - 1 do
		local angle = H.PLOT_FIRST_ANGLE - span / 2 + k * span
		Util.inlay({
			name = "SectorDivider",
			size = Vector3.new(H.DIVIDER_WIDTH, 0.2, r1 - r0),
			cframe = Util.radialFrame(angle, (r0 + r1) / 2, F + TRIM_TOP - 0.1),
			color = P.Trim,
			parent = folder,
		})
	end

	-- Promenade ring linking all four gates behind the plots.
	Util.arc({
		name = "PromenadeRing",
		radius = H.OUTER_RING_RADIUS,
		width = H.DIVIDER_WIDTH,
		fromDeg = 0,
		toDeg = 360,
		bottomY = F - 0.14,
		topY = F + TRIM_TOP,
		color = P.Trim,
		stepDeg = 3,
		decorative = true,
		parent = folder,
	})

	-- Green accents: one small arc in front of each plot, one curved strip behind it.
	local IG, BG = H.INNER_GREEN, H.BACK_GREEN
	for i = 1, H.PLOT_COUNT do
		local axis = plotAngle(H, i)
		Util.arc({
			name = "GreenAccent",
			radius = (IG.INNER + IG.OUTER) / 2,
			width = IG.OUTER - IG.INNER,
			fromDeg = axis - IG.HALF_SPAN,
			toDeg = axis + IG.HALF_SPAN,
			bottomY = F - 0.17,
			topY = F + INLAY_TOP,
			color = P.Green,
			stepDeg = 4,
			studs = "top",
			decorative = true,
			parent = folder,
		})
		for _, range in splitAround(axis - BG.HALF_SPAN, axis + BG.HALF_SPAN, H.GATE_ANGLES, BG.GATE_GAP) do
			Util.arc({
				name = "GreenAccent",
				radius = (BG.INNER + BG.OUTER) / 2,
				width = BG.OUTER - BG.INNER,
				fromDeg = range[1],
				toDeg = range[2],
				bottomY = F - 0.17,
				topY = F + INLAY_TOP,
				color = P.Green,
				stepDeg = 3,
				studs = "top",
				decorative = true,
				parent = folder,
			})
		end
	end

	-- Light approach path in front of every gate.
	local approachFrom = BG.INNER
	local approachTo = H.WALL_INNER_RADIUS - (H.GATE_DEPTH - H.WALL_THICKNESS) / 2
	for _, angle in H.GATE_ANGLES do
		Util.inlay({
			name = "GateApproach",
			size = Vector3.new(H.GATE_OPENING_WIDTH + 2, 0.2, approachTo - approachFrom),
			cframe = Util.radialFrame(angle, (approachFrom + approachTo) / 2, F + INLAY_TOP - 0.1),
			color = P.FloorLight,
			studs = "top",
			parent = folder,
		})
	end
end

local function buildPlots(hub: Instance, H, P)
	local plots = Util.folder("Plots", hub)
	local F = H.FLOOR_Y
	local W, D = H.PAD_WIDTH, H.PAD_DEPTH
	local fr = H.PAD_FRAME
	local margin = H.PAD_GREEN_MARGIN
	local centerRadius = H.PAD_INNER_RADIUS + D / 2
	local barBottom = -0.5

	for i = 1, H.PLOT_COUNT do
		local angle = plotAngle(H, i)
		local plot = Util.model("Plot" .. i, plots)
		plot:SetAttribute("PlotId", i)
		plot:SetAttribute("Angle", angle)

		-- LookVector points at the hub centre, so local X runs along the circumference
		-- (pad width) and local -Z is the side a future aquarium shows its glass on.
		local frame = Util.radialFrame(angle, centerRadius, F)
		local pad = Util.model("AquariumPad", plot)

		local anchor = Util.part({
			name = "AquariumAnchor",
			size = Vector3.new(W, 1, D),
			cframe = frame * CFrame.new(0, 0.5, 0),
			color = P.PadSurface,
			transparency = 1,
			collide = false,
			shadow = false,
			parent = pad,
		})
		anchor:SetAttribute("PlotId", i)
		pad.PrimaryPart = anchor

		Util.inlay({
			name = "PadGreenMargin",
			size = Vector3.new(W + 2 * margin, 0.2, D + 2 * margin),
			cframe = frame * CFrame.new(0, INLAY_TOP - 0.1, 0),
			color = P.Green,
			studs = "top",
			parent = pad,
		})

		local surfaceTop = H.PAD_SURFACE_HEIGHT
		Util.part({
			name = "PadSurface",
			size = Vector3.new(W - 2 * fr, surfaceTop - barBottom, D - 2 * fr),
			cframe = frame * CFrame.new(0, (surfaceTop + barBottom) / 2, 0),
			color = P.PadSurface,
			studs = "top",
			parent = pad,
		})

		local barTop = H.PAD_FRAME_HEIGHT
		local barHeight = barTop - barBottom
		local barY = (barTop + barBottom) / 2
		for _, side in { -1, 1 } do
			Util.part({
				name = if side < 0 then "PadFrameFront" else "PadFrameBack",
				size = Vector3.new(W, barHeight, fr),
				cframe = frame * CFrame.new(0, barY, side * (D / 2 - fr / 2)),
				color = P.PadFrame,
				studs = "top",
				parent = pad,
			})
			Util.part({
				name = "PadFrameSide",
				size = Vector3.new(fr, barHeight, D - 2 * fr),
				cframe = frame * CFrame.new(side * (W / 2 - fr / 2), barY, 0),
				color = P.PadFrame,
				studs = "top",
				parent = pad,
			})
		end

		-- Cyan line on the inward edge marks where the aquarium glass will face.
		Util.inlay({
			name = "GlassSideMarker",
			size = Vector3.new(W - 2 * fr, 0.1, fr * 0.6),
			cframe = frame * CFrame.new(0, barTop + 0.05, -(D / 2 - fr / 2)),
			color = P.PadFront,
			parent = pad,
		})
	end
end

local function isNearGate(H, angle: number, halfWidthDeg: number): boolean
	for _, gateAngle in H.GATE_ANGLES do
		if Util.angleDelta(angle, gateAngle) < halfWidthDeg then
			return true
		end
	end
	return false
end

local function buildWall(hub: Instance, H, P)
	local folder = Util.folder("Walls", hub)
	local F = H.FLOOR_Y
	local T = H.WALL_THICKNESS
	local rMid = H.WALL_INNER_RADIUS + T / 2
	local step = H.WALL_SEGMENT_DEG
	local towerReach = H.GATE_OPENING_WIDTH / 2 + H.GATE_TOWER_WIDTH
	local towerHalfDeg = math.deg(math.asin(towerReach / rMid))
	local length = 2 * (rMid + T / 2) * math.sin(math.rad(step / 2)) + 0.3
	local bottom = F - 5
	local top = F + H.WALL_HEIGHT

	for i = 0, 360 / step - 1 do
		local angle = step * (i + 0.5)
		-- Segments that would sit entirely inside a gate tower are skipped; the rest
		-- run into the towers so there is never a seam.
		if not isNearGate(H, angle, towerHalfDeg - step / 2) then
			Util.part({
				name = "Wall",
				size = Vector3.new(length, top - bottom, T),
				cframe = Util.radialFrame(angle, rMid, (top + bottom) / 2),
				color = P.Wall,
				studs = "all",
				parent = folder,
			})
			Util.part({
				name = "WallCap",
				size = Vector3.new(length + 0.2, 1, T + 1),
				cframe = Util.radialFrame(angle, rMid, top + 0.5),
				color = P.WallCap,
				studs = "top",
				parent = folder,
			})
		end
	end

	-- Pillars with integrated lanterns every 30 degrees; gates take the cardinal slots.
	local pillarTop = top + 4
	for angle = 0, 359, H.PILLAR_EVERY_DEG do
		if not isNearGate(H, angle, 1) then
			local pillar = Util.model("WallPillar", folder)
			Util.part({
				name = "Pillar",
				size = Vector3.new(8, pillarTop - bottom, 8),
				cframe = Util.radialFrame(angle, rMid, (pillarTop + bottom) / 2),
				color = P.Tower,
				studs = "all",
				parent = pillar,
			})
			Util.part({
				name = "PillarCap",
				size = Vector3.new(9.5, 1.2, 9.5),
				cframe = Util.radialFrame(angle, rMid, pillarTop + 0.6),
				color = P.TowerCap,
				studs = "top",
				parent = pillar,
			})
			lantern(pillar, Util.radialFrame(angle, rMid, pillarTop + 1.2), 1, P)
		end
	end
end

local function banner(parent: Instance, face: CFrame, P)
	-- face: frame on the tower's inner surface, LookVector pointing into the hub.
	Util.part({
		name = "BannerRod",
		size = Vector3.new(6, 0.4, 0.4),
		cframe = face * CFrame.new(0, 4.3, -0.4),
		color = P.LanternFrame,
		parent = parent,
	})
	Util.part({
		name = "Banner",
		size = Vector3.new(5, 8, 0.3),
		cframe = face * CFrame.new(0, 0, -0.2),
		color = P.Banner,
		shadow = false,
		parent = parent,
	})
	-- Simple blocky fish emblem.
	local emblem = face * CFrame.new(-0.4, 0.4, -0.4)
	Util.part({
		name = "BannerFish",
		size = Vector3.new(2.6, 1.3, 0.1),
		cframe = emblem,
		color = P.BannerEmblem,
		shadow = false,
		parent = parent,
	})
	for _, sign in { -1, 1 } do
		Util.part({
			name = "BannerFishTail",
			size = Vector3.new(1.2, 0.45, 0.1),
			cframe = emblem * CFrame.new(1.7, sign * 0.35, 0) * CFrame.Angles(0, 0, math.rad(sign * 35)),
			color = P.BannerEmblem,
			shadow = false,
			parent = parent,
		})
	end
	Util.part({
		name = "BannerFishEye",
		size = Vector3.new(0.3, 0.3, 0.12),
		cframe = emblem * CFrame.new(-0.75, 0.15, -0.02),
		color = P.Banner,
		shadow = false,
		parent = parent,
	})
end

local function buildGate(folder: Instance, Config, index: number, rng)
	local H, P, B = Config.Hub, Config.Palette, Config.Bubble
	local angle = H.GATE_ANGLES[index]
	local gate = Util.model("Gate_" .. H.GATE_NAMES[index], folder)
	gate:SetAttribute("Angle", angle)

	local F = H.FLOOR_Y
	local rMid = H.WALL_INNER_RADIUS + H.WALL_THICKNESS / 2
	local depth = H.GATE_DEPTH
	local halfOpen = H.GATE_OPENING_WIDTH / 2
	local spring = H.GATE_SPRING_HEIGHT
	local crown = spring + halfOpen
	local towerW = H.GATE_TOWER_WIDTH
	local towerX = halfOpen + towerW / 2
	local towerBottom = -5
	local towerTop = H.GATE_TOWER_HEIGHT

	-- Local frame: origin on the floor at the middle of the wall, X tangential,
	-- +Z outward (ocean side), -Z inward (hub side). Offsets below are relative to it.
	local g = Util.radialFrame(angle, rMid, F)
	local inner = -depth / 2

	for _, side in { -1, 1 } do
		Util.part({
			name = "GateTower",
			size = Vector3.new(towerW, towerTop - towerBottom, depth),
			cframe = g * CFrame.new(side * towerX, (towerTop + towerBottom) / 2, 0),
			color = P.Tower,
			studs = "all",
			parent = gate,
		})
		Util.part({
			name = "GateTowerCap",
			size = Vector3.new(towerW + 1.5, 1.5, depth + 1.5),
			cframe = g * CFrame.new(side * towerX, towerTop + 0.75, 0),
			color = P.TowerCap,
			studs = "top",
			parent = gate,
		})
		lantern(gate, g * CFrame.new(side * towerX, towerTop + 1.5, 0), 1.3, P)

		-- Paired wall lanterns flanking the opening on the hub side.
		Util.part({
			name = "SconceBracket",
			size = Vector3.new(1.2, 0.8, 2),
			cframe = g * CFrame.new(side * towerX, 6.6, inner - 1),
			color = P.LanternFrame,
			parent = gate,
		})
		lantern(gate, g * CFrame.new(side * towerX, 7, inner - 1.4), 0.75, P)

		banner(gate, g * CFrame.new(side * towerX, 15.5, inner), P)
	end

	-- Stepped header that forms the rounded opening, then a solid crown block.
	for row = 0, halfOpen - 1 do
		local openHalf = math.sqrt(math.max(0, halfOpen * halfOpen - row * row))
		local solid = halfOpen - openHalf
		if solid > 0.05 then
			for _, side in { -1, 1 } do
				Util.part({
					name = "GateHeader",
					size = Vector3.new(solid + 0.1, 1, depth),
					cframe = g * CFrame.new(side * (openHalf + solid / 2), spring + row + 0.5, 0),
					color = P.Tower,
					studs = "all",
					parent = gate,
				})
			end
		end
	end
	Util.part({
		name = "GateHeader",
		size = Vector3.new(2 * halfOpen + 0.2, towerTop - crown, depth),
		cframe = g * CFrame.new(0, (towerTop + crown) / 2, 0),
		color = P.Tower,
		studs = "all",
		parent = gate,
	})

	-- Lighter arch ring, jambs and keystone on both faces.
	local ringRadius = halfOpen + 0.9
	local segments = 9
	local segDeg = 180 / segments
	local segLength = 2 * (ringRadius + 0.9) * math.sin(math.rad(segDeg / 2)) + 0.2
	for _, face in { -1, 1 } do
		local z = face * (depth / 2 + 0.3)
		for k = 0, segments - 1 do
			local phi = math.rad(segDeg * (k + 0.5))
			Util.part({
				name = "ArchStone",
				size = Vector3.new(segLength, 1.8, 1),
				cframe = g
					* CFrame.new(ringRadius * math.cos(phi), spring + ringRadius * math.sin(phi), z)
					* CFrame.Angles(0, 0, phi + math.pi / 2),
				color = P.TowerCap,
				parent = gate,
			})
		end
		for _, side in { -1, 1 } do
			Util.part({
				name = "ArchJamb",
				size = Vector3.new(1.8, spring, 1),
				cframe = g * CFrame.new(side * ringRadius, spring / 2, z),
				color = P.TowerCap,
				parent = gate,
			})
		end
		Util.part({
			name = "ArchKeystone",
			size = Vector3.new(2.6, 2.6, 1.4),
			cframe = g * CFrame.new(0, crown + 0.9, z),
			color = P.WallCap,
			parent = gate,
		})
	end

	-- Walkway through the gate and down to the seabed on the ocean side.
	local platformEdge = H.PLATFORM_RADIUS
	local thresholdFrom = rMid - depth / 2
	Util.part({
		name = "GateThreshold",
		size = Vector3.new(2 * halfOpen + 4, 4.02, platformEdge - thresholdFrom),
		cframe = Util.radialFrame(angle, (thresholdFrom + platformEdge) / 2, F - 1.99),
		color = P.Threshold,
		studs = "top",
		parent = gate,
	})
	for stepIndex, stepTop in { -2, -4 } do
		local from = platformEdge + (stepIndex - 1) * 5
		Util.part({
			name = "GateStep",
			size = Vector3.new(2 * halfOpen + 4, stepTop + 10, 5),
			cframe = Util.radialFrame(angle, from + 2.5, F + (stepTop - 10) / 2),
			color = P.Threshold,
			studs = "top",
			parent = gate,
		})
	end

	-- Water curtain: the dry/wet boundary. The terrain water starts on this line too.
	local curtainZ = B.MEMBRANE_RADIUS - rMid
	local curtain = Util.part({
		name = "WaterCurtain",
		size = Vector3.new(2 * halfOpen, crown, 0.4),
		cframe = g * CFrame.new(0, crown / 2, curtainZ),
		color = P.WaterCurtain,
		material = Enum.Material.Glass,
		transparency = 0.45,
		collide = false,
		shadow = false,
		parent = gate,
	})
	curtain:SetAttribute("WaterCurtain", true)

	Util.part({
		name = "CurtainFoam",
		size = Vector3.new(2 * halfOpen, 0.5, 1.6),
		cframe = g * CFrame.new(0, 0.3, curtainZ),
		color = P.Foam,
		transparency = 0.35,
		collide = false,
		shadow = false,
		parent = gate,
	})

	-- Falling streaks, animated on each client by GateWaterfalls.
	local streaks = Util.folder("Streaks", gate)
	local lanes = 14
	for lane = 0, lanes - 1 do
		local width = rng.range(0.5, 1)
		local x = -halfOpen + 0.8 + (2 * halfOpen - 1.6) * lane / (lanes - 1) + rng.range(-0.2, 0.2)
		local length = rng.range(2.5, 5.5)
		local edge = math.min(halfOpen - 0.05, math.abs(x) + width / 2)
		local topY = F + spring + math.sqrt(halfOpen * halfOpen - edge * edge) - 1
		local bottomY = F + 0.4
		local range = math.max(0.5, topY - bottomY - length)
		local phase = rng.range(0, range)
		local streakZ = curtainZ + (if lane % 2 == 0 then -0.3 else 0.3)
		local streak = Util.part({
			name = "Streak",
			size = Vector3.new(width, length, 0.15),
			cframe = g * CFrame.new(x, topY - F - length / 2 - phase, streakZ),
			color = P.WaterStreak,
			transparency = 0.45,
			collide = false,
			shadow = false,
			parent = streaks,
		})
		streak:SetAttribute("TopY", topY)
		streak:SetAttribute("BottomY", bottomY)
		streak:SetAttribute("Speed", rng.range(11, 17))
		streak:SetAttribute("Phase", phase)
	end
	return gate
end

local function buildSpawn(hub: Instance, H)
	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "HubSpawn"
	spawn.Anchored = true
	spawn.Size = Vector3.new(6, 1, 6)
	local pos = Util.polar(H.SPAWN_ANGLE, H.SPAWN_RADIUS, H.FLOOR_Y - 0.45)
	-- Characters spawn with the SpawnLocation's rotation, so this faces them at the plaza.
	spawn.CFrame = CFrame.lookAt(pos, Vector3.new(0, pos.Y, 0))
	spawn.Transparency = 1
	spawn.CanCollide = false
	spawn.CanQuery = false
	spawn.CastShadow = false
	spawn.Neutral = true
	spawn.Duration = 0
	spawn.Parent = hub
	return spawn
end

function HubBuilder.build(parent: Instance, Config): Model
	local H, P = Config.Hub, Config.Palette
	local hub = Util.model("Hub", parent)
	buildFloor(hub, H, P)
	buildPattern(hub, H, P)
	buildPlots(hub, H, P)
	buildWall(hub, H, P)
	local gates = Util.folder("Gates", hub)
	local rng = Util.newRng(Config.SEED + 11)
	for index = 1, #H.GATE_ANGLES do
		buildGate(gates, Config, index, rng)
	end
	buildSpawn(hub, H)
	return hub
end

HubBuilder.plotAngle = plotAngle

return HubBuilder
