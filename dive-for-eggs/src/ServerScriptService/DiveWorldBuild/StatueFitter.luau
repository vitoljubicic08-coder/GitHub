-- Fits an imported statue model into the plaza without touching its artwork:
-- anchors it, turns off detailed collision, scales it uniformly, centres its base on the
-- plaza floor, adds one simple invisible collision cylinder, and gives the lanterns that
-- are part of the model a warm glow and a small PointLight each.
-- Mesh shape and lantern positions come from the EditableMesh/EditableImage APIs when
-- Studio allows it; otherwise part bounding boxes and part names/colours are used.

local AssetService = game:GetService("AssetService")

local Util = require(script.Parent.Util)

local StatueFitter = {}

local LANTERN_WORDS = { "lantern", "lamp", "torch", "candle" }
local GLOW_WORDS = { "glow", "bulb", "flame", "emiss" }
local HELPER_NAMES = { StatueCollision = true, LanternLights = true, LanternLight = true }
local MAX_SAMPLE_POINTS = 60000

local function nameHas(instance: Instance, words: { string }): boolean
	local lower = string.lower(instance.Name)
	for _, word in words do
		if string.find(lower, word, 1, true) then
			return true
		end
	end
	return false
end

local function isHelper(instance: Instance): boolean
	local node = instance
	while node do
		if HELPER_NAMES[node.Name] then
			return true
		end
		node = node.Parent
	end
	return false
end

local function artParts(model: Model): { BasePart }
	local parts = {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and not isHelper(d) then
			table.insert(parts, d)
		end
	end
	return parts
end

local function isTextured(part: BasePart): boolean
	if part:FindFirstChildOfClass("SurfaceAppearance") then
		return true
	end
	return part:IsA("MeshPart") and (part :: MeshPart).TextureID ~= ""
end

local function isWarmGlow(r: number, g: number, b: number): boolean
	return r >= 0.78 and g >= 0.5 and g <= 0.97 and b <= 0.62 and r - b >= 0.3
end

------------------------------------------------------------------------ mesh access

type MeshEntry = {
	part: MeshPart,
	editable: any,
	vertices: { number },
	positions: { [number]: Vector3 },
	centre: Vector3,
	size: Vector3,
}

local function contentFor(instance: Instance, contentProperty: string, uriProperty: string): any
	local ok, content = pcall(function()
		return (instance :: any)[contentProperty]
	end)
	if ok and content ~= nil and content.Uri ~= nil and content.Uri ~= "" then
		return content
	end
	local uri = (instance :: any)[uriProperty]
	if uri == nil or uri == "" then
		return nil
	end
	return Content.fromUri(uri)
end

local function readMesh(part: MeshPart): MeshEntry?
	local ok, entry = pcall(function()
		local content = contentFor(part, "MeshContent", "MeshId")
		if not content then
			return nil
		end
		local editable = AssetService:CreateEditableMeshAsync(content)
		local vertices = editable:GetVertices()
		local positions = {}
		local lo, hi = Vector3.one * math.huge, -Vector3.one * math.huge
		for _, id in vertices do
			local p = editable:GetPosition(id)
			positions[id] = p
			lo = Vector3.new(math.min(lo.X, p.X), math.min(lo.Y, p.Y), math.min(lo.Z, p.Z))
			hi = Vector3.new(math.max(hi.X, p.X), math.max(hi.Y, p.Y), math.max(hi.Z, p.Z))
		end
		if #vertices == 0 then
			return nil
		end
		local size = hi - lo
		return {
			part = part,
			editable = editable,
			vertices = vertices,
			positions = positions,
			centre = (lo + hi) / 2,
			size = Vector3.new(math.max(size.X, 1e-4), math.max(size.Y, 1e-4), math.max(size.Z, 1e-4)),
		}
	end)
	return if ok then entry else nil
end

-- Mesh-space vertex position to world space, following the part's current size.
local function toWorld(entry: MeshEntry, p: Vector3): Vector3
	local part = entry.part
	return part.CFrame * ((p - entry.centre) * (part.Size / entry.size))
end

local function boxCorners(part: BasePart): { Vector3 }
	local out = {}
	local half = part.Size / 2
	for _, sx in { -1, 1 } do
		for _, sy in { -1, 1 } do
			for _, sz in { -1, 1 } do
				table.insert(out, part.CFrame * Vector3.new(sx * half.X, sy * half.Y, sz * half.Z))
			end
		end
	end
	return out
end

------------------------------------------------------------------------ shape measurement

type Shape = {
	minY: number,
	height: number,
	base: Vector3, -- centre of the footprint at floor level
	baseRadius: number,
	reach: number, -- widest horizontal extent from the base axis (fins, coral, ...)
	precise: boolean,
}

local function samplePoints(parts: { BasePart }, meshes: { [BasePart]: MeshEntry }): ({ Vector3 }, boolean)
	local total = 0
	for _, entry in meshes do
		total += #entry.vertices
	end
	local stride = math.max(1, math.ceil(total / MAX_SAMPLE_POINTS))
	local points, precise = {}, true
	for _, part in parts do
		local entry = meshes[part]
		if entry then
			for i = 1, #entry.vertices, stride do
				table.insert(points, toWorld(entry, entry.positions[entry.vertices[i]]))
			end
		else
			precise = precise and not part:IsA("MeshPart")
			for _, corner in boxCorners(part) do
				table.insert(points, corner)
			end
		end
	end
	return points, precise
end

local function measure(points: { Vector3 }, precise: boolean): Shape
	local minY, maxY = math.huge, -math.huge
	for _, p in points do
		minY, maxY = math.min(minY, p.Y), math.max(maxY, p.Y)
	end
	local height = maxY - minY
	local baseTop = minY + math.max(0.12 * height, 0.2)
	local lo, hi = Vector3.one * math.huge, -Vector3.one * math.huge
	for _, p in points do
		if p.Y <= baseTop then
			lo = Vector3.new(math.min(lo.X, p.X), 0, math.min(lo.Z, p.Z))
			hi = Vector3.new(math.max(hi.X, p.X), 0, math.max(hi.Z, p.Z))
		end
	end
	local base = Vector3.new((lo.X + hi.X) / 2, minY, (lo.Z + hi.Z) / 2)
	local baseRadius, reach = 0, 0
	for _, p in points do
		local d = math.sqrt((p.X - base.X) ^ 2 + (p.Z - base.Z) ^ 2)
		reach = math.max(reach, d)
		if p.Y <= baseTop then
			baseRadius = math.max(baseRadius, d)
		end
	end
	if not precise then
		-- Only box corners are known: the round base fits inside the box, not around it.
		-- (Reach keeps the corner distance, which errs on the safe side for the stalls.)
		baseRadius = math.max(hi.X - lo.X, hi.Z - lo.Z) / 2
	end
	return {
		minY = minY,
		height = height,
		base = base,
		baseRadius = baseRadius,
		reach = reach,
		precise = precise,
	}
end

------------------------------------------------------------------------ lanterns

type Spot = { position: Vector3, count: number }

-- Groups nearby points into clusters (lantern glow panels).
local function cluster(points: { Vector3 }, cell: number): { Spot }
	local parent = {}
	local function find(i)
		while parent[i] ~= i do
			parent[i] = parent[parent[i]]
			i = parent[i]
		end
		return i
	end
	local grid = {}
	local function key(x, y, z)
		return string.format("%d,%d,%d", x, y, z)
	end
	for i, p in points do
		parent[i] = i
		local gx, gy, gz = math.floor(p.X / cell), math.floor(p.Y / cell), math.floor(p.Z / cell)
		for dx = -1, 1 do
			for dy = -1, 1 do
				for dz = -1, 1 do
					local bucket = grid[key(gx + dx, gy + dy, gz + dz)]
					if bucket then
						for _, j in bucket do
							if (points[j] - p).Magnitude <= cell then
								local a, b = find(i), find(j)
								if a ~= b then
									parent[a] = b
								end
							end
						end
					end
				end
			end
		end
		local k = key(gx, gy, gz)
		grid[k] = grid[k] or {}
		table.insert(grid[k], i)
	end
	local groups = {}
	for i, p in points do
		local root = find(i)
		local g = groups[root]
		if not g then
			g = { sum = Vector3.zero, count = 0 }
			groups[root] = g
		end
		g.sum += p
		g.count += 1
	end
	local spots = {}
	for _, g in groups do
		table.insert(spots, { position = g.sum / g.count, count = g.count })
	end
	return spots
end

-- Keeps clusters that sit in the lower part of the statue on a common ring, which is how
-- lanterns around a circular base look; drops stray warm spots such as a yellow fish.
local function ringFilter(spots: { Spot }, shape: Shape, minCount: number): { Spot }
	local low = {}
	for _, spot in spots do
		if spot.count >= minCount and spot.position.Y <= shape.minY + 0.55 * shape.height then
			table.insert(low, spot)
		end
	end
	if #low < 2 then
		return low
	end
	local radii = {}
	for _, spot in low do
		local p = spot.position
		table.insert(radii, math.sqrt((p.X - shape.base.X) ^ 2 + (p.Z - shape.base.Z) ^ 2))
	end
	local sorted = table.clone(radii)
	table.sort(sorted)
	local median = sorted[math.ceil(#sorted / 2)]
	local kept = {}
	for i, spot in low do
		if math.abs(radii[i] - median) <= 0.35 * median + 0.5 then
			table.insert(kept, spot)
		end
	end
	return kept
end

local function readTexture(part: MeshPart): (buffer?, number, number)
	local ok, pixels, w, h = pcall(function()
		local source: Instance = part:FindFirstChildOfClass("SurfaceAppearance") or part
		local content = if source:IsA("SurfaceAppearance")
			then contentFor(source, "ColorMapContent", "ColorMap")
			else contentFor(part, "TextureContent", "TextureID")
		if not content then
			return nil, 0, 0
		end
		local image = AssetService:CreateEditableImageAsync(content)
		local size = image.Size
		local data = image:ReadPixelsBuffer(Vector2.zero, size)
		image:Destroy()
		return data, size.X, size.Y
	end)
	if ok and pixels then
		return pixels, w, h
	end
	return nil, 0, 0
end

-- Finds warm, bright texels on the mesh (painted lantern glass) and returns their world
-- positions. Both UV orientations are tried because exporters disagree on V.
local function warmTexturePoints(entry: MeshEntry): ({ Vector3 }, { Vector3 })
	local pixels, w, h = readTexture(entry.part)
	if not pixels then
		return {}, {}
	end
	local asIs, flipped = {}, {}
	pcall(function()
		local mesh = entry.editable
		for _, face in mesh:GetFaces() do
			local uvIds = mesh:GetFaceUVs(face)
			if uvIds and #uvIds >= 3 then
				local u, v = 0, 0
				for _, id in uvIds do
					local uv = mesh:GetUV(id)
					u += uv.X
					v += uv.Y
				end
				u, v = u / #uvIds, v / #uvIds
				local px = math.clamp(math.floor(u * w), 0, w - 1)
				local centroid = nil
				for pass, vv in { v, 1 - v } do
					local py = math.clamp(math.floor(vv * h), 0, h - 1)
					local i = (py * w + px) * 4
					local r = buffer.readu8(pixels, i) / 255
					local g = buffer.readu8(pixels, i + 1) / 255
					local b = buffer.readu8(pixels, i + 2) / 255
					if isWarmGlow(r, g, b) then
						if not centroid then
							local sum = Vector3.zero
							local verts = mesh:GetFaceVertices(face)
							for _, vid in verts do
								sum += entry.positions[vid] or mesh:GetPosition(vid)
							end
							centroid = toWorld(entry, sum / #verts)
						end
						table.insert(if pass == 1 then asIs else flipped, centroid)
					end
				end
			end
		end
	end)
	return asIs, flipped
end

local function findLanterns(model: Model, parts: { BasePart }, meshes, shape: Shape, P): ({ Spot }, string)
	local cell = math.max(0.8, shape.height * 0.04)

	-- 1. Markers the user dropped into the model by hand.
	local markers = {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and d.Name == "LanternMarker" then
			table.insert(markers, { position = d.Position, count = 1 })
		end
	end
	if #markers > 0 then
		return markers, "LanternMarker parts"
	end

	-- 2. Separate glow panels: named glow parts, or small untextured warm parts low down.
	local glow = {}
	for _, part in parts do
		local c = part.Color
		local small = math.max(part.Size.X, part.Size.Y, part.Size.Z) <= 0.15 * shape.height
		local low = part.Position.Y <= shape.minY + 0.6 * shape.height
		local named = nameHas(part, GLOW_WORDS) and not nameHas(part, LANTERN_WORDS)
		if named or (small and low and not isTextured(part) and isWarmGlow(c.R, c.G, c.B)) then
			table.insert(glow, part)
		end
	end
	if #glow > 0 then
		local points = {}
		for _, part in glow do
			-- Only the light-emitting piece glows; textured meshes keep their artwork.
			if not isTextured(part) then
				part.Material = Enum.Material.Neon
				part.Color = P.StatueLanternGlow
			end
			table.insert(points, part.Position)
		end
		return cluster(points, cell), string.format("%d glow part(s) in the model", #glow)
	end

	-- 3. Whole lantern parts by name (lights only; their look is left alone).
	local named = {}
	for _, part in parts do
		if nameHas(part, LANTERN_WORDS) then
			table.insert(named, part.Position)
		end
	end
	if #named > 0 then
		return cluster(named, cell), "lantern parts found by name"
	end

	-- 4. Painted lanterns on a single textured mesh.
	local best, bestCount = {}, 0
	for _, entry in meshes do
		local asIs, flipped = warmTexturePoints(entry)
		for _, candidate in { asIs, flipped } do
			local spots = ringFilter(cluster(candidate, cell), shape, 3)
			if #spots > bestCount and #spots <= 32 then
				best, bestCount = spots, #spots
			end
		end
	end
	if bestCount >= 2 then
		return best, "warm lantern glass found in the statue texture"
	end
	return {}, "none found"
end

------------------------------------------------------------------------ fitting

export type FitResult = {
	shape: Shape,
	scale: number,
	lanterns: number,
	lanternMethod: string,
	notes: { string },
}

function StatueFitter.fit(model: Model, Config, floorCentre: Vector3, maxRadius: number): FitResult
	local S, P = Config.Statue, Config.Palette
	local notes = {}

	for _, name in { "StatueCollision", "LanternLights" } do
		local old = model:FindFirstChild(name)
		if old then
			old:Destroy()
		end
	end

	local parts = artParts(model)
	for _, part in parts do
		part.Anchored = true
		part.CanCollide = false
		part.CanTouch = false
	end

	local meshes = {}
	for _, part in parts do
		if part:IsA("MeshPart") then
			local entry = readMesh(part)
			if entry then
				meshes[part] = entry
			end
		end
	end

	local function shapeNow(): Shape
		return measure(samplePoints(parts, meshes))
	end

	-- Uniform scale: as tall as the target, but never wider than the space the stalls leave.
	local before = shapeNow()
	if before.height <= 0 then
		error("the selected statue has no visible size")
	end
	local k = math.min(S.TARGET_HEIGHT / before.height, maxRadius / math.max(before.reach, 1e-3))
	model:ScaleTo(model:GetScale() * k)

	-- Optional turn about the base axis; remembered so re-running does not add it twice.
	local applied = model:GetAttribute("DiveYawDegrees") or 0
	local turn = S.YAW_DEGREES - applied
	if turn ~= 0 then
		local axis = shapeNow().base
		local spin = CFrame.new(axis) * CFrame.Angles(0, math.rad(turn), 0) * CFrame.new(-axis)
		model:PivotTo(spin * model:GetPivot())
		model:SetAttribute("DiveYawDegrees", S.YAW_DEGREES)
	end

	-- Base centre onto the plaza centre, bottom onto the floor.
	local placed = shapeNow()
	model:PivotTo(model:GetPivot() + (floorCentre - placed.base))
	local shape = shapeNow()

	if shape.height < S.MIN_HEIGHT then
		table.insert(
			notes,
			string.format(
				"statue is only %.1f studs tall because it is wide (%.1f stud reach); widen Stalls.RADIUS for a taller statue",
				shape.height,
				shape.reach
			)
		)
	end
	if not shape.precise then
		table.insert(notes, "mesh shape could not be read, so size and collision use part bounding boxes")
	end

	-- One simple invisible collision cylinder around the base; the art itself does not collide.
	local collisionRadius = math.min(shape.baseRadius, maxRadius)
	local collisionHeight = math.min(S.COLLISION_HEIGHT, shape.height)
	local collision = Instance.new("Part")
	collision.Name = "StatueCollision"
	collision.Shape = Enum.PartType.Cylinder
	collision.Size = Vector3.new(collisionHeight, collisionRadius * 2, collisionRadius * 2)
	collision.CFrame = CFrame.new(floorCentre + Vector3.new(0, collisionHeight / 2, 0)) * CFrame.Angles(0, 0, math.rad(90))
	collision.Anchored = true
	collision.CanCollide = true
	collision.CanTouch = false
	collision.CastShadow = false
	collision.Transparency = 1
	collision.Parent = model

	-- Lanterns: warm glow on the light panels where they are separate, and one small
	-- PointLight per lantern.
	local spots, method = findLanterns(model, parts, meshes, shape, P)
	if #spots > 0 then
		local folder = Util.folder("LanternLights", model)
		for i, spot in spots do
			local outward = Vector3.new(spot.position.X - shape.base.X, 0, spot.position.Z - shape.base.Z)
			local nudge = if outward.Magnitude > 1e-3 then outward.Unit * 0.25 else Vector3.zero
			local holder = Util.part({
				name = "LanternLight",
				size = Vector3.new(0.4, 0.4, 0.4),
				cframe = CFrame.new(spot.position + nudge),
				color = P.StatueLanternLight,
				transparency = 1,
				collide = false,
				shadow = false,
				parent = folder,
			})
			holder:SetAttribute("Index", i)
			local light = Instance.new("PointLight")
			light.Color = P.StatueLanternLight
			light.Brightness = S.LANTERN_LIGHT.BRIGHTNESS
			light.Range = S.LANTERN_LIGHT.RANGE
			light.Shadows = false
			light.Parent = holder
		end
	end
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and d.Name == "LanternMarker" then
			d:Destroy()
		end
	end

	for _, entry in meshes do
		pcall(function()
			entry.editable:Destroy()
		end)
	end

	return {
		shape = shape,
		scale = k,
		lanterns = #spots,
		lanternMethod = method,
		notes = notes,
	}
end

return StatueFitter
