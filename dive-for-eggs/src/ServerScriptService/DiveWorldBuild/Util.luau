-- Small building helpers shared by the world builders.

local Util = {}

-- Deterministic xorshift32. Roblox's Random is not available to the offline preview, and
-- the preview must place every coral and rock exactly where a live server does.
export type Rng = {
	next: () -> number,
	range: (lo: number, hi: number) -> number,
	int: (lo: number, hi: number) -> number,
	pick: <T>(list: { T }) -> T,
}

function Util.newRng(seed: number): Rng
	local state = seed % 4294967296
	if state == 0 then
		state = 0x9E3779B9
	end
	local rng = {} :: any
	function rng.next(): number
		state = bit32.bxor(state, bit32.lshift(state, 13))
		state = bit32.bxor(state, bit32.rshift(state, 17))
		state = bit32.bxor(state, bit32.lshift(state, 5))
		return state / 4294967296
	end
	function rng.range(lo: number, hi: number): number
		return lo + (hi - lo) * rng.next()
	end
	function rng.int(lo: number, hi: number): number
		return math.min(hi, lo + math.floor((hi - lo + 1) * rng.next()))
	end
	function rng.pick(list)
		return list[rng.int(1, #list)]
	end
	return rng
end

-- Unit direction for a compass angle (degrees clockwise from north / -Z).
function Util.dir(angleDeg: number): Vector3
	local a = math.rad(angleDeg)
	return Vector3.new(math.sin(a), 0, -math.cos(a))
end

function Util.polar(angleDeg: number, radius: number, y: number): Vector3
	return Util.dir(angleDeg) * radius + Vector3.new(0, y, 0)
end

-- Frame at a polar position whose LookVector points at the hub axis. Local X is then the
-- tangent (clockwise), local Z points outward, so sizes read (tangential, height, radial).
function Util.radialFrame(angleDeg: number, radius: number, y: number): CFrame
	local pos = Util.polar(angleDeg, radius, y)
	return CFrame.lookAt(pos, pos - Util.dir(angleDeg))
end

function Util.angleOf(x: number, z: number): number
	return math.deg(math.atan2(x, -z)) % 360
end

function Util.angleDelta(a: number, b: number): number
	return math.abs((a - b + 180) % 360 - 180)
end

function Util.lerp(a: number, b: number, t: number): number
	return a + (b - a) * t
end

function Util.smoothstep(t: number): number
	t = math.clamp(t, 0, 1)
	return t * t * (3 - 2 * t)
end

function Util.quantize(value: number, step: number): number
	return math.floor(value / step + 0.5) * step
end

-- Colour from a height ramp ({ y, color } sorted from high to low).
function Util.ramp(stops: { { y: number, color: Color3 } }, y: number): Color3
	if y >= stops[1].y then
		return stops[1].color
	end
	for i = 2, #stops do
		local a, b = stops[i - 1], stops[i]
		if y >= b.y then
			return a.color:Lerp(b.color, (a.y - y) / (a.y - b.y))
		end
	end
	return stops[#stops].color
end

export type PartSpec = {
	name: string?,
	size: Vector3,
	cframe: CFrame,
	color: Color3,
	material: Enum.Material?,
	studs: ("top" | "all")?,
	transparency: number?,
	reflectance: number?,
	collide: boolean?,
	shadow: boolean?,
	parent: Instance?,
}

local SURFACE_FACES = { "TopSurface", "BottomSurface", "FrontSurface", "BackSurface", "LeftSurface", "RightSurface" }

function Util.part(spec: PartSpec): Part
	local part = Instance.new("Part")
	part.Name = spec.name or "Part"
	part.Anchored = true
	part.Size = spec.size
	part.CFrame = spec.cframe
	part.Color = spec.color
	part.Transparency = spec.transparency or 0
	part.Reflectance = spec.reflectance or 0
	part.CastShadow = if spec.shadow == nil then true else spec.shadow
	for _, face in SURFACE_FACES do
		(part :: any)[face] = Enum.SurfaceType.Smooth
	end
	if spec.studs then
		part.Material = spec.material or Enum.Material.Plastic
		part.TopSurface = Enum.SurfaceType.Studs
		if spec.studs == "all" then
			part.FrontSurface = Enum.SurfaceType.Studs
			part.BackSurface = Enum.SurfaceType.Studs
			part.LeftSurface = Enum.SurfaceType.Studs
			part.RightSurface = Enum.SurfaceType.Studs
			part.BottomSurface = Enum.SurfaceType.Inlet
		end
	else
		part.Material = spec.material or Enum.Material.SmoothPlastic
	end
	if spec.collide == false then
		part.CanCollide = false
		part.CanTouch = false
		part.CanQuery = false
	end
	part.Parent = spec.parent
	return part
end

-- Thin decorative part that is effectively floor: no collision, never blocks the camera.
function Util.inlay(spec: PartSpec): Part
	spec.collide = false
	spec.shadow = false
	return Util.part(spec)
end

-- Ring or arc of straight segments centred on the hub axis.
export type ArcSpec = {
	name: string,
	radius: number, -- centre-line radius
	width: number, -- radial width
	fromDeg: number,
	toDeg: number,
	bottomY: number,
	topY: number,
	color: Color3,
	stepDeg: number?,
	studs: ("top" | "all")?,
	decorative: boolean?, -- inlay: no collision/shadow
	parent: Instance,
}

function Util.arc(spec: ArcSpec): { Part }
	local span = spec.toDeg - spec.fromDeg
	local count = math.max(1, math.ceil(span / (spec.stepDeg or 4)))
	local step = span / count
	-- Chord of the outer edge plus a little overlap so segments close without gaps.
	local outer = spec.radius + spec.width / 2
	local length = 2 * outer * math.sin(math.rad(step / 2)) + 0.3
	local height = spec.topY - spec.bottomY
	local parts = {}
	for i = 0, count - 1 do
		local angle = spec.fromDeg + step * (i + 0.5)
		local partSpec: PartSpec = {
			name = spec.name,
			size = Vector3.new(length, height, spec.width),
			cframe = Util.radialFrame(angle, spec.radius, spec.bottomY + height / 2),
			color = spec.color,
			studs = spec.studs,
			parent = spec.parent,
		}
		table.insert(parts, if spec.decorative then Util.inlay(partSpec) else Util.part(partSpec))
	end
	return parts
end

-- Filled disc made of axis-aligned studded strips (Roblox does not render studs on
-- cylinders). Strip edges land on whole studs so the stud grid lines up across strips.
function Util.disc(
	parent: Instance,
	name: string,
	radius: number,
	strip: number,
	bottomY: number,
	topY: number,
	color: Color3,
	decorative: boolean?
): { Part }
	local parts = {}
	local rows = math.ceil(radius / strip)
	for row = -rows, rows - 1 do
		local z0, z1 = row * strip, (row + 1) * strip
		local zMid = (z0 + z1) / 2
		local nearest = math.min(math.abs(z0), math.abs(z1))
		local reach = if decorative then zMid else nearest
		local halfWidth = math.sqrt(math.max(0, radius * radius - reach * reach))
		halfWidth = if decorative then math.floor(halfWidth) else math.ceil(halfWidth)
		if halfWidth > 0 then
			local spec: PartSpec = {
				name = name,
				size = Vector3.new(halfWidth * 2, topY - bottomY, strip),
				cframe = CFrame.new(0, (topY + bottomY) / 2, zMid),
				color = color,
				studs = "top",
				parent = parent,
			}
			table.insert(parts, if decorative then Util.inlay(spec) else Util.part(spec))
		end
	end
	return parts
end

function Util.folder(name: string, parent: Instance): Folder
	local folder = Instance.new("Folder")
	folder.Name = name
	folder.Parent = parent
	return folder
end

function Util.model(name: string, parent: Instance): Model
	local model = Instance.new("Model")
	model.Name = name
	model.Parent = parent
	return model
end

return Util
