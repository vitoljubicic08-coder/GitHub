-- Geometry helpers over the built (mock) instance tree: bounding boxes, footprints and a
-- height raster of the seabed, used by the acceptance checks and the preview exporter.

local Vector3 = require("./roblox").Vector3

local Scene = {}

function Scene.parts(root)
	local out = {}
	for _, d in root:GetDescendants() do
		if d:IsA("BasePart") then
			table.insert(out, d)
		end
	end
	return out
end

-- World-space axis-aligned bounds: centre and half extents.
function Scene.aabb(part)
	local c = part.CFrame
	local s = part.Size
	local rx, ry, rz = c.RightVector, c.UpVector, c.ZVector
	local hx = (math.abs(rx.X) * s.X + math.abs(ry.X) * s.Y + math.abs(rz.X) * s.Z) / 2
	local hy = (math.abs(rx.Y) * s.X + math.abs(ry.Y) * s.Y + math.abs(rz.Y) * s.Z) / 2
	local hz = (math.abs(rx.Z) * s.X + math.abs(ry.Z) * s.Y + math.abs(rz.Z) * s.Z) / 2
	return c.Position, Vector3.new(hx, hy, hz)
end

function Scene.top(part): number
	local centre, half = Scene.aabb(part)
	return centre.Y + half.Y
end

-- True when (x, z) lies inside the footprint of an upright part.
function Scene.covers(part, x: number, z: number): boolean
	local c = part.CFrame
	local dx, dz = x - c.Position.X, z - c.Position.Z
	local right, back = c.RightVector, c.ZVector
	local lx = dx * right.X + dz * right.Z
	local lz = dx * back.X + dz * back.Z
	return math.abs(lx) <= part.Size.X / 2 + 1e-6 and math.abs(lz) <= part.Size.Z / 2 + 1e-6
end

-- Height raster of solid seabed parts (highest top per cell). Floating overhang slabs
-- and cave roofs are left out so the raster describes the ground you would land on.
function Scene.heightRaster(seabedFolder, cell: number, halfExtent: number)
	local n = math.floor(2 * halfExtent / cell)
	local grid = {}
	for _, part in Scene.parts(seabedFolder) do
		if part.Name ~= "Overhang" and part.Name ~= "CaveRoof" and part.Name ~= "Massif" then
			local centre, half = Scene.aabb(part)
			local top = centre.Y + half.Y
			local x0 = math.max(0, math.floor((centre.X - half.X + halfExtent) / cell + 0.5))
			local x1 = math.min(n - 1, math.floor((centre.X + half.X + halfExtent) / cell + 0.5) - 1)
			local z0 = math.max(0, math.floor((centre.Z - half.Z + halfExtent) / cell + 0.5))
			local z1 = math.min(n - 1, math.floor((centre.Z + half.Z + halfExtent) / cell + 0.5) - 1)
			for ix = x0, x1 do
				for iz = z0, z1 do
					local i = ix * n + iz
					if grid[i] == nil or top > grid[i] then
						grid[i] = top
					end
				end
			end
		end
	end
	return function(x: number, z: number): number?
		local ix = math.floor((x + halfExtent) / cell)
		local iz = math.floor((z + halfExtent) / cell)
		if ix < 0 or iz < 0 or ix >= n or iz >= n then
			return nil
		end
		return grid[ix * n + iz]
	end
end

return Scene
