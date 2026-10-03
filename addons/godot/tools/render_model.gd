extends SceneTree
## Renders a model from four sides (front = looking at its +z face, right, back, top) into one PNG, to check
## orientation and look. Needs a window:
##   godot_console --path . --resolution 512x512 -s res://tools/render_model.gd -- --scene=res://x.glb --out=res://.verify/x.png

func _initialize() -> void:
	_run.call_deferred()

func _arg(n: String) -> String:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--%s=" % n):
			return a.trim_prefix("--%s=" % n)
	return ""

func _run() -> void:
	var stage := Node3D.new()
	root.add_child(stage)
	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.55, 0.57, 0.6)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.8, 0.8, 0.85)
	env.ambient_light_energy = 0.7
	we.environment = env
	stage.add_child(we)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45, 30, 0)
	stage.add_child(sun)
	var model: Node3D = (load(_arg("scene")) as PackedScene).instantiate()
	stage.add_child(model)
	var bb := AABB()
	var first := true
	for mi in model.find_children("*", "MeshInstance3D", true, false):
		var b: AABB = mi.global_transform * mi.get_aabb() if mi.skin == null else model.global_transform * mi.get_aabb()
		bb = b if first else bb.merge(b)
		first = false
	var c := bb.get_center()
	var r := bb.size.length() * 0.8
	var cam := Camera3D.new()
	cam.fov = 40
	stage.add_child(cam)
	cam.make_current()
	var views := [Vector3(0, 0.3, 1), Vector3(1, 0.3, 0), Vector3(0, 0.3, -1), Vector3(0, 1, 0.001)]
	var sheet := Image.create(1024, 1024, false, Image.FORMAT_RGBA8)
	for i in views.size():
		cam.global_position = c + views[i].normalized() * r * 1.4
		cam.look_at(c, Vector3.UP if i < 3 else Vector3.FORWARD)
		for f in 6:
			await process_frame
		await RenderingServer.frame_post_draw
		var img := root.get_texture().get_image()
		img.resize(512, 512)
		img.convert(Image.FORMAT_RGBA8)
		sheet.blit_rect(img, Rect2i(0, 0, 512, 512), Vector2i((i % 2) * 512, (i / 2) * 512))
	sheet.save_png(_arg("out"))
	print("RENDERED ", _arg("out"), " size ", bb.size)
	quit(0)
