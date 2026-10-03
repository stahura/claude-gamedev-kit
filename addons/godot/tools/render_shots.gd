extends SceneTree
## Renders the fixed shot set (docs/shots/shots.json, see docs/visual-pipeline.md) to one PNG per shot. Needs a
## window or a GPU (not --headless, which renders nothing); always pass --quit-after as a failsafe, and --fixed-fps 60
## so shader TIME (wind, water) advances the same per frame on every run:
##   godot_console --path . --resolution 1920x1080 --fixed-fps 60 --quit-after 20000 -s res://tools/render_shots.gd -- --out=docs/shots/_work/r1/P1/i1 [--set=res://docs/shots/shots.json] [--only=shot-01-x,shot-02-y]
## Repeatable: the global RNG is seeded per shot (set "seed", default 1) before the scene loads; after settle_frames the
## tree is paused and Engine.time_scale set to 0 for the capture. Fails (exit 1) on a missing scene, an unreadable set,
## or a saved PNG whose size is not the set's resolution (the OS can clamp the window, e.g. 1080p on a 1080p screen).
## Prints SHOT lines.
## Benchmark (no PNGs): -- --bench=600 [--bench-shot=shot-01-wide] holds the shot's camera with vsync off and prints
##   BENCH avg_fps=<x> low1_fps=<y> frames=<n>   (check it with python tools/perf_gate.py --phase P<N> <log>)
## Tested with Godot 4.7.2 (Forward+, Vulkan, Windows GPU window).

func _initialize() -> void:
	_run.call_deferred()

func _arg(n: String, def := "") -> String:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--%s=" % n):
			return a.trim_prefix("--%s=" % n)
	return def

func _v3(a: Array) -> Vector3:
	return Vector3(float(a[0]), float(a[1]), float(a[2]))

func _fail(msg: String) -> void:
	push_error(msg)
	printerr("RENDER FAIL: " + msg)
	quit(1)

func _stage(shot: Dictionary, rng_seed: int) -> Node:
	var ps := load(shot.scene) as PackedScene
	if ps == null:
		return null
	seed(rng_seed)
	paused = false
	Engine.time_scale = 1.0
	var scene := ps.instantiate()
	root.add_child(scene)
	var cam := Camera3D.new()
	cam.fov = float(shot.get("fov", 50))
	scene.add_child(cam)
	cam.global_position = _v3(shot.pos)
	cam.look_at(_v3(shot.look_at), Vector3.UP)
	cam.make_current()
	return scene

func _bench(data: Dictionary, frames: int) -> void:
	var want := _arg("bench-shot")
	var shot: Dictionary = data.shots[0]
	for s in data.shots:
		if s.name == want:
			shot = s
	var scene := _stage(shot, int(data.get("seed", 1)))
	if scene == null:
		_fail("missing scene %s for %s" % [shot.scene, shot.name])
		return
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	for f in int(data.get("settle_frames", 30)):
		await process_frame
	var times: Array[float] = []
	var last := Time.get_ticks_usec()
	for f in frames:
		await process_frame
		var now := Time.get_ticks_usec()
		times.append(float(now - last))
		last = now
	var total := 0.0
	for t in times:
		total += t
	times.sort()
	times.reverse()
	var k: int = max(1, times.size() / 100)
	var worst := 0.0
	for i in k:
		worst += times[i]
	print("BENCH avg_fps=%.1f low1_fps=%.1f frames=%d shot=%s" % [
		1e6 * times.size() / total, 1e6 * k / worst, times.size(), shot.name])
	quit(0)

func _run() -> void:
	var set_path := _arg("set", "res://docs/shots/shots.json")
	var data = JSON.parse_string(FileAccess.get_file_as_string(set_path))
	if typeof(data) != TYPE_DICTIONARY or not data.has("shots") or data.shots.is_empty():
		_fail("unreadable shot set " + set_path)
		return
	var want := Vector2i.ZERO
	if data.has("resolution"):
		want = Vector2i(int(data.resolution[0]), int(data.resolution[1]))
		root.size = want
	var bench := int(_arg("bench", "0"))
	if bench > 0:
		await _bench(data, bench)
		return
	var out := _arg("out", "docs/shots/_work/latest")
	if not out.is_absolute_path():
		out = ProjectSettings.globalize_path("res://").path_join(out)
	DirAccess.make_dir_recursive_absolute(out)
	var only := _arg("only").split(",", false)
	var settle: int = int(data.get("settle_frames", 30))
	for shot in data.shots:
		if only.size() > 0 and not only.has(shot.name):
			continue
		var scene := _stage(shot, int(data.get("seed", 1)))
		if scene == null:
			_fail("missing scene %s for %s" % [shot.scene, shot.name])
			return
		for f in settle:
			await process_frame
		paused = true
		Engine.time_scale = 0.0
		await process_frame
		await RenderingServer.frame_post_draw
		var path := out.path_join("%s.png" % shot.name)
		root.get_texture().get_image().save_png(path)
		var saved := Image.load_from_file(path)
		if saved == null or (want != Vector2i.ZERO and saved.get_size() != want):
			_fail("%s saved at %s, the set needs %s (window clamped? use a smaller set resolution or a bigger screen)"
				% [path, saved.get_size() if saved else "nothing", want])
			return
		print("SHOT %s v%d %dx%d -> %s" % [shot.name, int(data.get("version", 0)), saved.get_width(), saved.get_height(), path])
		scene.queue_free()
		paused = false
		Engine.time_scale = 1.0
		await process_frame
	print("SHOTS DONE")
	quit(0)
