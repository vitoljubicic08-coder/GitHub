-- Builds the starter world when a server starts, unless it is already baked into the place.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage:WaitForChild("DiveWorld"):WaitForChild("Config"))

if workspace:FindFirstChild(Config.WORLD_FOLDER_NAME) then
	return
end

local WorldBuilder = require(script.WorldBuilder)

-- Hold character spawning until the floor exists so nobody drops into the void.
local autoLoads = Players.CharacterAutoLoads
Players.CharacterAutoLoads = false
local ok, err = pcall(WorldBuilder.build)
Players.CharacterAutoLoads = autoLoads
if not ok then
	warn("[DiveWorld] Starter world build failed: " .. tostring(err))
end
if autoLoads then
	for _, player in Players:GetPlayers() do
		if not player.Character then
			player:LoadCharacter()
		end
	end
end
