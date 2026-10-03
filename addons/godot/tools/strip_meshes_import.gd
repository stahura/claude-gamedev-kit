@tool
extends EditorScenePostImport
## Post-import script for animation-clip GLBs (set as import_script/path in their .import files): Meshy clip GLBs
## carry the whole textured mesh; only the AnimationPlayer is used, so the meshes are dropped to keep the pck small.

func _post_import(scene: Node) -> Object:
	for mi in scene.find_children("*", "MeshInstance3D", true, false):
		mi.get_parent().remove_child(mi)
		mi.free()
	return scene
