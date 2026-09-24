-- Builds (or rebuilds) the whole starter world. Safe to run repeatedly: the previous
-- DiveStarterWorld folder is removed first. Run from the Studio command bar to bake it:
--   require(game.ServerScriptService.DiveWorldBuild.WorldBuilder).build()

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage:WaitForChild("DiveWorld"):WaitForChild("Config"))
local HubBuilder = require(script.Parent.HubBuilder)
local BubbleBuilder = require(script.Parent.BubbleBuilder)
local SeabedShape = require(script.Parent.SeabedShape)
local SeabedBuilder = require(script.Parent.SeabedBuilder)
local DecorBuilder = require(script.Parent.DecorBuilder)
local WaterBuilder = require(script.Parent.WaterBuilder)
local LightingBuilder = require(script.Parent.LightingBuilder)

local WorldBuilder = {}

function WorldBuilder.build(): Folder
	local old = workspace:FindFirstChild(Config.WORLD_FOLDER_NAME)
	if old then
		old:Destroy()
	end

	-- Build unparented, then parent once: much faster than replicating part by part.
	local world = Instance.new("Folder")
	world.Name = Config.WORLD_FOLDER_NAME
	world:SetAttribute("Layout", "SixPlazaHub")

	HubBuilder.build(world, Config)
	BubbleBuilder.build(world, Config)
	local shape = SeabedShape.new(Config)
	local ground = SeabedBuilder.build(world, Config, shape)
	DecorBuilder.build(world, Config, shape, ground)
	WaterBuilder.build(Config)
	LightingBuilder.build(Config)

	-- The abyss sits just above Roblox's default destroy height; give swimmers margin.
	-- Only plugins and the command bar may set this, so live servers keep the default.
	pcall(function()
		workspace.FallenPartsDestroyHeight = math.min(workspace.FallenPartsDestroyHeight, Config.Ocean.BOTTOM_Y - 100)
	end)

	world.Parent = workspace
	return world
end

return WorldBuilder
