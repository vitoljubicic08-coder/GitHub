-- Minimal Roblox API stand-in so the world builders can run under Lune.
-- Only what the builders touch is implemented; anything else errors loudly.

local M = {}

----------------------------------------------------------------------------- Vector3
local Vector3 = {}
Vector3.__index = function(v, key)
	if key == "X" then
		return rawget(v, "x")
	elseif key == "Y" then
		return rawget(v, "y")
	elseif key == "Z" then
		return rawget(v, "z")
	elseif key == "Magnitude" then
		return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
	elseif key == "Unit" then
		local m = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
		return Vector3.new(v.x / m, v.y / m, v.z / m)
	end
	return Vector3[key]
end
function Vector3.new(x, y, z)
	return setmetatable({ x = x or 0, y = y or 0, z = z or 0, __type = "Vector3" }, Vector3)
end
Vector3.__add = function(a, b)
	return Vector3.new(a.x + b.x, a.y + b.y, a.z + b.z)
end
Vector3.__sub = function(a, b)
	return Vector3.new(a.x - b.x, a.y - b.y, a.z - b.z)
end
Vector3.__mul = function(a, b)
	if type(a) == "number" then
		return Vector3.new(b.x * a, b.y * a, b.z * a)
	elseif type(b) == "number" then
		return Vector3.new(a.x * b, a.y * b, a.z * b)
	end
	return Vector3.new(a.x * b.x, a.y * b.y, a.z * b.z)
end
Vector3.__div = function(a, b)
	return Vector3.new(a.x / b, a.y / b, a.z / b)
end
Vector3.__unm = function(a)
	return Vector3.new(-a.x, -a.y, -a.z)
end
Vector3.__eq = function(a, b)
	return a.x == b.x and a.y == b.y and a.z == b.z
end
Vector3.__tostring = function(v)
	return string.format("%g, %g, %g", v.x, v.y, v.z)
end
function Vector3.Dot(a, b)
	return a.x * b.x + a.y * b.y + a.z * b.z
end
function Vector3.Cross(a, b)
	return Vector3.new(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)
end
function Vector3.Lerp(a, b, t)
	return a + (b - a) * t
end
Vector3.zero = Vector3.new(0, 0, 0)
Vector3.one = Vector3.new(1, 1, 1)
Vector3.xAxis = Vector3.new(1, 0, 0)
Vector3.yAxis = Vector3.new(0, 1, 0)
Vector3.zAxis = Vector3.new(0, 0, 1)
M.Vector3 = { new = Vector3.new, zero = Vector3.zero, one = Vector3.one, xAxis = Vector3.xAxis, yAxis = Vector3.yAxis, zAxis = Vector3.zAxis }

----------------------------------------------------------------------------- CFrame
-- Stored as position p and rotation columns rx, ry, rz (= Right, Up, -Look).
local CFrame = {}
local function cf(p, rx, ry, rz)
	return setmetatable({ p = p, rx = rx, ry = ry, rz = rz, __type = "CFrame" }, CFrame)
end
local function rotate(c, v)
	return c.rx * v.x + c.ry * v.y + c.rz * v.z
end
CFrame.__index = function(c, key)
	if key == "Position" then
		return c.p
	elseif key == "X" then
		return c.p.x
	elseif key == "Y" then
		return c.p.y
	elseif key == "Z" then
		return c.p.z
	elseif key == "LookVector" then
		return -c.rz
	elseif key == "RightVector" or key == "XVector" then
		return c.rx
	elseif key == "UpVector" or key == "YVector" then
		return c.ry
	elseif key == "ZVector" then
		return c.rz
	elseif key == "Rotation" then
		return cf(Vector3.zero, c.rx, c.ry, c.rz)
	end
	return CFrame[key]
end
CFrame.__mul = function(a, b)
	if getmetatable(b) == CFrame then
		return cf(a.p + rotate(a, b.p), rotate(a, b.rx), rotate(a, b.ry), rotate(a, b.rz))
	end
	return a.p + rotate(a, b)
end
CFrame.__add = function(a, v)
	return cf(a.p + v, a.rx, a.ry, a.rz)
end
CFrame.__sub = function(a, v)
	return cf(a.p - v, a.rx, a.ry, a.rz)
end
function CFrame.Inverse(c)
	-- Transpose of the rotation.
	local rx = Vector3.new(c.rx.x, c.ry.x, c.rz.x)
	local ry = Vector3.new(c.rx.y, c.ry.y, c.rz.y)
	local rz = Vector3.new(c.rx.z, c.ry.z, c.rz.z)
	local inv = cf(Vector3.zero, rx, ry, rz)
	return cf(-rotate(inv, c.p), rx, ry, rz)
end
function CFrame.PointToWorldSpace(c, v)
	return c * v
end
function CFrame.PointToObjectSpace(c, v)
	return c:Inverse() * v
end
function CFrame.VectorToWorldSpace(c, v)
	return rotate(c, v)
end
function CFrame.GetComponents(c)
	return c.p.x, c.p.y, c.p.z, c.rx.x, c.ry.x, c.rz.x, c.rx.y, c.ry.y, c.rz.y, c.rx.z, c.ry.z, c.rz.z
end

local function cfNew(x, y, z)
	if x == nil then
		return cf(Vector3.zero, Vector3.xAxis, Vector3.yAxis, Vector3.zAxis)
	elseif type(x) == "table" then
		return cf(x, Vector3.xAxis, Vector3.yAxis, Vector3.zAxis)
	end
	return cf(Vector3.new(x, y, z), Vector3.xAxis, Vector3.yAxis, Vector3.zAxis)
end
local function cfLookAt(at, target, up)
	up = up or Vector3.yAxis
	local look = (target - at).Unit
	local right = look:Cross(up).Unit
	local newUp = right:Cross(look)
	return cf(at, right, newUp, -look)
end
local function axisRot(axis, a)
	local c, s = math.cos(a), math.sin(a)
	if axis == "x" then
		return cf(Vector3.zero, Vector3.new(1, 0, 0), Vector3.new(0, c, s), Vector3.new(0, -s, c))
	elseif axis == "y" then
		return cf(Vector3.zero, Vector3.new(c, 0, -s), Vector3.new(0, 1, 0), Vector3.new(s, 0, c))
	end
	return cf(Vector3.zero, Vector3.new(c, s, 0), Vector3.new(-s, c, 0), Vector3.new(0, 0, 1))
end
local function cfAngles(rx, ry, rz)
	return axisRot("x", rx) * axisRot("y", ry) * axisRot("z", rz)
end
M.CFrame = { new = cfNew, lookAt = cfLookAt, Angles = cfAngles, fromEulerAnglesXYZ = cfAngles, identity = cfNew() }

----------------------------------------------------------------------------- Color3
local Color3 = {}
Color3.__index = Color3
local function color(r, g, b)
	return setmetatable({ R = r, G = g, B = b, __type = "Color3" }, Color3)
end
function Color3.Lerp(a, b, t)
	return color(a.R + (b.R - a.R) * t, a.G + (b.G - a.G) * t, a.B + (b.B - a.B) * t)
end
function Color3.ToHex(c)
	return string.format("%02x%02x%02x", math.floor(c.R * 255 + 0.5), math.floor(c.G * 255 + 0.5), math.floor(c.B * 255 + 0.5))
end
M.Color3 = {
	new = color,
	fromRGB = function(r, g, b)
		return color(r / 255, g / 255, b / 255)
	end,
}

----------------------------------------------------------------------------- Enum
M.Enum = setmetatable({}, {
	__index = function(enums, enumType)
		local items = setmetatable({}, {
			__index = function(list, name)
				local item = { Name = name, EnumType = enumType, __type = "EnumItem" }
				rawset(list, name, item)
				return item
			end,
		})
		rawset(enums, enumType, items)
		return items
	end,
})

----------------------------------------------------------------------------- Instances
local Instance = {}
local CLASS_DEFAULTS = {
	Part = function(p)
		p.Size = Vector3.new(4, 1, 2)
		p.CFrame = cfNew()
		p.Color = M.Color3.fromRGB(163, 162, 165)
		p.Transparency = 0
		p.Reflectance = 0
		p.Anchored = false
		p.CanCollide = true
		p.CanTouch = true
		p.CanQuery = true
		p.CastShadow = true
		p.Material = M.Enum.Material.Plastic
	end,
}
CLASS_DEFAULTS.SpawnLocation = CLASS_DEFAULTS.Part
CLASS_DEFAULTS.MeshPart = function(p)
	CLASS_DEFAULTS.Part(p)
	p.MeshId = ""
	p.TextureID = ""
end

local IS_A = {
	BasePart = { Part = true, SpawnLocation = true, MeshPart = true },
	PVInstance = { Part = true, SpawnLocation = true, MeshPart = true, Model = true },
	Part = { Part = true, SpawnLocation = true },
	Folder = { Folder = true },
	Model = { Model = true },
	Atmosphere = { Atmosphere = true },
	ColorCorrectionEffect = { ColorCorrectionEffect = true },
}

local instanceMeta = {}
instanceMeta.__index = function(inst, key)
	local method = Instance[key]
	if method then
		return method
	end
	local props = rawget(inst, "_props")
	if key == "Parent" then
		return rawget(inst, "_parent")
	elseif key == "Position" and props.CFrame then
		return props.CFrame.p
	end
	local value = props[key]
	if value ~= nil then
		return value
	end
	local child = inst:FindFirstChild(key)
	if child then
		return child
	end
	error(string.format("mock: %s.%s is not set or not supported", rawget(inst, "ClassName"), tostring(key)), 2)
end
instanceMeta.__newindex = function(inst, key, value)
	if key == "Parent" then
		local old = rawget(inst, "_parent")
		if old then
			local siblings = rawget(old, "_children")
			for i, c in siblings do
				if c == inst then
					table.remove(siblings, i)
					break
				end
			end
		end
		rawset(inst, "_parent", value)
		if value then
			table.insert(rawget(value, "_children"), inst)
		end
		return
	elseif key == "Position" then
		local c = rawget(inst, "_props").CFrame or cfNew()
		rawget(inst, "_props").CFrame = cf(value, c.rx, c.ry, c.rz)
		return
	elseif key == "CanQuery" and value == false and rawget(inst, "_props").CanCollide ~= false then
		error("mock: CanQuery can only be false when CanCollide is false", 2)
	end
	rawget(inst, "_props")[key] = value
end

local function newInstance(className)
	local inst = setmetatable({
		ClassName = className,
		_props = { Name = className },
		_children = {},
		_attributes = {},
	}, instanceMeta)
	local defaults = CLASS_DEFAULTS[className]
	if defaults then
		defaults(rawget(inst, "_props"))
	end
	return inst
end

function Instance.FindFirstChild(inst, name)
	for _, c in rawget(inst, "_children") do
		if rawget(c, "_props").Name == name then
			return c
		end
	end
	return nil
end
Instance.WaitForChild = function(inst, name)
	return inst:FindFirstChild(name) or error("mock: WaitForChild(" .. name .. ") would hang", 2)
end
function Instance.FindFirstChildOfClass(inst, className)
	for _, c in rawget(inst, "_children") do
		if rawget(c, "ClassName") == className then
			return c
		end
	end
	return nil
end
function Instance.GetChildren(inst)
	return table.clone(rawget(inst, "_children"))
end
function Instance.GetDescendants(inst)
	local out = {}
	local function walk(node)
		for _, c in rawget(node, "_children") do
			table.insert(out, c)
			walk(c)
		end
	end
	walk(inst)
	return out
end
function Instance.IsA(inst, className)
	local cls = rawget(inst, "ClassName")
	if cls == className then
		return true
	end
	local set = IS_A[className]
	return set ~= nil and set[cls] == true
end
function Instance.Destroy(inst)
	inst.Parent = nil
end
function Instance.SetAttribute(inst, key, value)
	rawget(inst, "_attributes")[key] = value
end
function Instance.GetAttribute(inst, key)
	return rawget(inst, "_attributes")[key]
end
function Instance.GetFullName(inst)
	local names = {}
	local node = inst
	while node do
		table.insert(names, 1, rawget(node, "_props").Name)
		node = rawget(node, "_parent")
	end
	return table.concat(names, ".")
end

function Instance.IsDescendantOf(inst, ancestor)
	local node = rawget(inst, "_parent")
	while node do
		if node == ancestor then
			return true
		end
		node = rawget(node, "_parent")
	end
	return false
end
function Instance.FindFirstAncestorWhichIsA(inst, className)
	local node = rawget(inst, "_parent")
	while node do
		if node:IsA(className) then
			return node
		end
		node = rawget(node, "_parent")
	end
	return nil
end
function Instance.FindFirstChildWhichIsA(inst, className)
	for _, c in rawget(inst, "_children") do
		if c:IsA(className) then
			return c
		end
	end
	return nil
end

-- Deep copy, remapping PrimaryPart to the copy's own part like Roblox does.
function Instance.Clone(inst)
	local map = {}
	local function copy(node)
		local clone = setmetatable({
			ClassName = rawget(node, "ClassName"),
			_props = table.clone(rawget(node, "_props")),
			_children = {},
			_attributes = table.clone(rawget(node, "_attributes")),
			_source = rawget(node, "_source"),
			_scale = rawget(node, "_scale"),
		}, instanceMeta)
		map[node] = clone
		for _, child in rawget(node, "_children") do
			local c = copy(child)
			rawset(c, "_parent", clone)
			table.insert(rawget(clone, "_children"), c)
		end
		return clone
	end
	local root = copy(inst)
	for original, clone in map do
		local primary = rawget(original, "_props").PrimaryPart
		if primary and map[primary] then
			rawget(clone, "_props").PrimaryPart = map[primary]
		end
	end
	return root
end

local function boxCentre(inst)
	local lo, hi = nil, nil
	for _, d in inst:GetDescendants() do
		if d:IsA("BasePart") then
			local p = d.CFrame.p
			lo = if lo then Vector3.new(math.min(lo.x, p.x), math.min(lo.y, p.y), math.min(lo.z, p.z)) else p
			hi = if hi then Vector3.new(math.max(hi.x, p.x), math.max(hi.y, p.y), math.max(hi.z, p.z)) else p
		end
	end
	return if lo then (lo + hi) / 2 else Vector3.zero
end

function Instance.GetPivot(inst)
	local props = rawget(inst, "_props")
	if inst:IsA("BasePart") then
		return props.CFrame
	elseif props.PrimaryPart then
		return props.PrimaryPart.CFrame
	elseif props.WorldPivot then
		return props.WorldPivot
	end
	return cfNew(boxCentre(inst))
end

function Instance.PivotTo(inst, target)
	local delta = target * inst:GetPivot():Inverse()
	if inst:IsA("BasePart") then
		inst.CFrame = target
		return
	end
	for _, d in inst:GetDescendants() do
		if d:IsA("BasePart") then
			d.CFrame = delta * d.CFrame
		end
	end
	local props = rawget(inst, "_props")
	if not props.PrimaryPart then
		props.WorldPivot = target
	end
end

function Instance.GetScale(inst)
	return rawget(inst, "_scale") or 1
end

function Instance.ScaleTo(inst, scale)
	local k = scale / inst:GetScale()
	local pivot = inst:GetPivot()
	local inverse = pivot:Inverse()
	for _, d in inst:GetDescendants() do
		if d:IsA("BasePart") then
			local rel = inverse * d.CFrame
			d.CFrame = pivot * cf(rel.p * k, rel.rx, rel.ry, rel.rz)
			d.Size = d.Size * k
		end
	end
	rawset(inst, "_scale", scale)
end

M.Instance = { new = newInstance }

----------------------------------------------------------------------------- DataModel
local game = newInstance("DataModel")
game.Name = "game"
local services = {}
for _, name in
	{
		"Workspace",
		"Lighting",
		"ReplicatedStorage",
		"ServerScriptService",
		"ServerStorage",
		"Players",
		"StarterPlayer",
		"Selection",
		"ChangeHistoryService",
		"AssetService",
	}
do
	local service = newInstance(name)
	service.Name = name
	service.Parent = game
	services[name] = service
end
function Instance.GetService(_, name)
	return services[name] or error("mock: unknown service " .. name, 2)
end

local starterPlayerScripts = newInstance("StarterPlayerScripts")
starterPlayerScripts.Name = "StarterPlayerScripts"
starterPlayerScripts.Parent = services.StarterPlayer

local workspace = services.Workspace
workspace.Gravity = 196.2
local terrain = newInstance("Terrain")
terrain.Name = "Terrain"
terrain.Parent = workspace
M.terrainOps = {}
function Instance.FillBlock(_, cframe, size, material)
	table.insert(M.terrainOps, { op = "block", cframe = cframe, size = size, material = material.Name })
end
function Instance.FillCylinder(_, cframe, height, radius, material)
	table.insert(M.terrainOps, { op = "cylinder", cframe = cframe, height = height, radius = radius, material = material.Name })
end
function Instance.FillBall(_, center, radius, material)
	table.insert(M.terrainOps, { op = "ball", center = center, radius = radius, material = material.Name })
end

local players = services.Players
players.CharacterAutoLoads = true
function Instance.GetPlayerFromCharacter()
	return nil
end
function Instance.GetPlayers()
	return {}
end

-- Studio-only services used by the plaza update tool.
M.selection = {}
function Instance.Get(_)
	return table.clone(M.selection)
end
function Instance.Set(_, list)
	M.selection = list
end
M.waypoints = {}
function Instance.SetWaypoint(_, name)
	table.insert(M.waypoints, name)
end
function Instance.CreateEditableMeshAsync()
	error("mock: EditableMesh is not available offline")
end
function Instance.CreateEditableImageAsync()
	error("mock: EditableImage is not available offline")
end

M.Content = {
	fromUri = function(uri)
		return { Uri = uri }
	end,
	fromAssetId = function(id)
		return { Uri = "rbxassetid://" .. tostring(id) }
	end,
}

M.game = game
M.workspace = workspace

return M
