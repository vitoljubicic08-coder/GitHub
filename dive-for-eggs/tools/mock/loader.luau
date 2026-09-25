-- Mounts the Rojo source tree into the mock DataModel and provides a Roblox-style
-- require, so the real builder modules run unchanged under Lune.

local fs = require("@lune/fs")
local luau = require("@lune/luau")
local task = require("@lune/task")

local roblox = require("./roblox")

local Loader = {}
Loader.roblox = roblox

local cache = {}
local requireModule

local function environment(scriptInstance)
	return {
		script = scriptInstance,
		game = roblox.game,
		workspace = roblox.workspace,
		Instance = roblox.Instance,
		Vector3 = roblox.Vector3,
		CFrame = roblox.CFrame,
		Color3 = roblox.Color3,
		Enum = roblox.Enum,
		Content = roblox.Content,
		require = requireModule,
		warn = function(...)
			print("[warn]", ...)
		end,
		task = { wait = function() end, spawn = task.spawn },
	}
end

function requireModule(target)
	if cache[target] ~= nil then
		return cache[target]
	end
	-- Scripts mounted from src/ carry a file path; scripts created at runtime (the Studio
	-- installer) carry their Source like real ones.
	local path = rawget(target, "_source")
	local source = if path then fs.readFile(path) else target.Source
	local chunk = luau.load(source, { debugName = path or target:GetFullName(), environment = environment(target) })
	local result = chunk()
	cache[target] = result
	return result
end

local function newScript(className: string, name: string, path: string, parent)
	local inst = roblox.Instance.new(className)
	inst.Name = name
	rawset(inst, "_source", path)
	inst.Parent = parent
	return inst
end

local function mount(dir: string, parent)
	local entries = fs.readDir(dir)
	table.sort(entries)
	for _, entry in entries do
		local full = dir .. "/" .. entry
		if fs.isDir(full) then
			local inst
			if fs.isFile(full .. "/init.server.luau") then
				inst = newScript("Script", entry, full .. "/init.server.luau", parent)
			else
				inst = roblox.Instance.new("Folder")
				inst.Name = entry
				inst.Parent = parent
			end
			mount(full, inst)
		elseif entry ~= "init.server.luau" then
			local name, kind = string.match(entry, "^(.-)%.(%a+)%.luau$")
			if name and kind == "server" then
				newScript("Script", name, full, parent)
			elseif name and kind == "client" then
				newScript("LocalScript", name, full, parent)
			elseif string.match(entry, "%.luau$") then
				newScript("ModuleScript", string.gsub(entry, "%.luau$", ""), full, parent)
			end
		end
	end
end

-- srcRoot: the project's src directory (ReplicatedStorage, ServerScriptService, ...).
function Loader.mountProject(srcRoot: string)
	for _, serviceName in fs.readDir(srcRoot) do
		local service = roblox.game:GetService(serviceName)
		mount(srcRoot .. "/" .. serviceName, service)
	end
end

Loader.require = function(target)
	return requireModule(target)
end

-- Runs a chunk (e.g. the generated Studio installer) the way the command bar would.
function Loader.runChunk(source: string, name: string)
	return luau.load(source, { debugName = name, environment = environment(nil) })()
end

-- Builds the world with the real WorldBuilder and returns (world folder, Config).
function Loader.buildWorld(srcRoot: string)
	Loader.mountProject(srcRoot)
	local sss = roblox.game:GetService("ServerScriptService")
	local builder = requireModule(sss.DiveWorldBuild.WorldBuilder)
	local config = requireModule(roblox.game:GetService("ReplicatedStorage").DiveWorld.Config)
	local world = builder.build()
	return world, config
end

return Loader
