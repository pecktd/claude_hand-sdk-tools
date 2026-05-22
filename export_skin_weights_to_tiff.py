"""
Export skin cluster influence weights as 16-bit TIFFs, one file per UDIM tile.

Only influences whose maximum weight on the mesh is non-zero are written.
Filenames follow the UDIM convention: <influence>.<udim>.tif
    e.g. lft_index_1_jnt.1001.tif

Caller (Maya Script Editor, Python tab):

import sys
sys.path.insert(0, r"C:\\dev\\hand_pose_with_sdk")
from importlib import reload
import export_skin_weights_to_tiff
reload(export_skin_weights_to_tiff)
export_skin_weights_to_tiff.SkinWeightTiffExporter(
    skin_cluster="skinCluster1",
    output_dir=r"C:\\temp\\weight_maps",
    resolution=2048,
).run()
"""

import os

import numpy as np

from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

import OpenImageIO as oiio


class SkinWeightTiffExporter:

    ACTIVE_EPSILON = 1.0e-6

    def __init__(self, skin_cluster, output_dir, resolution=2048):
        self.skin_cluster = skin_cluster
        self.output_dir = output_dir
        self.resolution = int(resolution)

    def run(self):
        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)

        skin_fn, mesh_path = self._resolve_skin_and_mesh()
        influence_names = self._influence_names(skin_fn)
        weights = self._gather_weights(skin_fn, mesh_path)
        triangles = self._gather_triangles(mesh_path)

        max_per_influence = weights.max(axis=0)
        active = [i for i, m in enumerate(max_per_influence) if m > self.ACTIVE_EPSILON]
        if not active:
            print("[skin-weights] No active influences found.")
            return

        print(
            "[skin-weights] Exporting {} of {} influences from '{}'.".format(
                len(active), len(influence_names), self.skin_cluster
            )
        )

        for idx in active:
            self._export_influence(influence_names[idx], weights[:, idx], triangles)

    def _resolve_skin_and_mesh(self):
        sel = om.MSelectionList()
        sel.add(self.skin_cluster)
        skin_obj = sel.getDependNode(0)
        if not skin_obj.hasFn(om.MFn.kSkinClusterFilter):
            raise ValueError("{} is not a skinCluster node.".format(self.skin_cluster))
        skin_fn = oma.MFnSkinCluster(skin_obj)
        shape_obj = skin_fn.getOutputGeometry()[0]
        mesh_path = om.MDagPath.getAPathTo(shape_obj)
        return skin_fn, mesh_path

    @staticmethod
    def _influence_names(skin_fn):
        return [dag.partialPathName().split("|")[-1] for dag in skin_fn.influenceObjects()]

    @staticmethod
    def _gather_weights(skin_fn, mesh_path):
        mesh_fn = om.MFnMesh(mesh_path)
        vert_count = mesh_fn.numVertices

        comp_fn = om.MFnSingleIndexedComponent()
        comp_obj = comp_fn.create(om.MFn.kMeshVertComponent)
        comp_fn.addElements(range(vert_count))

        flat, infl_count = skin_fn.getWeights(mesh_path, comp_obj)
        return np.array(flat, dtype=np.float32).reshape(vert_count, infl_count)

    @staticmethod
    def _gather_triangles(mesh_path):
        mesh_fn = om.MFnMesh(mesh_path)
        u_array, v_array = mesh_fn.getUVs()
        u_array = np.asarray(u_array, dtype=np.float64)
        v_array = np.asarray(v_array, dtype=np.float64)

        triangles = []
        it = om.MItMeshPolygon(mesh_path)
        while not it.isDone():
            if not it.hasUVs():
                it.next()
                continue

            face_verts = list(it.getVertices())
            vert_to_local = {v: i for i, v in enumerate(face_verts)}
            face_uvs = [it.getUVIndex(i) for i in range(len(face_verts))]

            for ti in range(it.numTriangles()):
                _, tri_verts = it.getTriangle(ti, om.MSpace.kObject)
                tri_verts = list(tri_verts)
                tri_uvs = [
                    (
                        u_array[face_uvs[vert_to_local[v]]],
                        v_array[face_uvs[vert_to_local[v]]],
                    )
                    for v in tri_verts
                ]
                triangles.append((tri_verts, tri_uvs))

            it.next()
        return triangles

    def _export_influence(self, influence_name, vertex_weights, triangles):
        res = self.resolution
        tile_images = {}

        for tri_verts, tri_uvs in triangles:
            w0 = float(vertex_weights[tri_verts[0]])
            w1 = float(vertex_weights[tri_verts[1]])
            w2 = float(vertex_weights[tri_verts[2]])
            if w0 == 0.0 and w1 == 0.0 and w2 == 0.0:
                continue

            us = [uv[0] for uv in tri_uvs]
            vs = [uv[1] for uv in tri_uvs]
            ut_lo = int(np.floor(min(us)))
            ut_hi = int(np.floor(max(us) - 1.0e-9))
            vt_lo = int(np.floor(min(vs)))
            vt_hi = int(np.floor(max(vs) - 1.0e-9))

            for ut in range(ut_lo, ut_hi + 1):
                if ut < 0 or ut > 9:
                    continue
                for vt in range(vt_lo, vt_hi + 1):
                    if vt < 0:
                        continue
                    udim = 1001 + ut + vt * 10
                    if udim not in tile_images:
                        tile_images[udim] = np.zeros((res, res), dtype=np.float32)
                    local_uvs = [(uv[0] - ut, uv[1] - vt) for uv in tri_uvs]
                    self._rasterize_triangle(tile_images[udim], local_uvs, (w0, w1, w2), res)

        for udim, img in tile_images.items():
            self._write_tiff(img, influence_name, udim)

    @staticmethod
    def _rasterize_triangle(image, uvs, weights, res):
        p0x = uvs[0][0] * res
        p0y = uvs[0][1] * res
        p1x = uvs[1][0] * res
        p1y = uvs[1][1] * res
        p2x = uvs[2][0] * res
        p2y = uvs[2][1] * res
        w0, w1, w2 = weights

        bx_min = max(0, int(np.floor(min(p0x, p1x, p2x))))
        bx_max = min(res - 1, int(np.ceil(max(p0x, p1x, p2x))))
        by_min = max(0, int(np.floor(min(p0y, p1y, p2y))))
        by_max = min(res - 1, int(np.ceil(max(p0y, p1y, p2y))))
        if bx_max < bx_min or by_max < by_min:
            return

        xs, ys = np.meshgrid(
            np.arange(bx_min, bx_max + 1, dtype=np.float32),
            np.arange(by_min, by_max + 1, dtype=np.float32),
            indexing="xy",
        )
        px = xs + 0.5
        py = ys + 0.5

        denom = (p1y - p2y) * (p0x - p2x) + (p2x - p1x) * (p0y - p2y)
        if abs(denom) < 1.0e-12:
            return

        a = ((p1y - p2y) * (px - p2x) + (p2x - p1x) * (py - p2y)) / denom
        b = ((p2y - p0y) * (px - p2x) + (p0x - p2x) * (py - p2y)) / denom
        c = 1.0 - a - b

        inside = (a >= 0.0) & (b >= 0.0) & (c >= 0.0)
        if not inside.any():
            return

        vals = (a * w0 + b * w1 + c * w2).astype(np.float32)

        # Maya UV (0,0) is bottom-left; image row 0 is top — flip Y.
        img_ys = (res - 1) - ys.astype(np.int32)
        img_xs = xs.astype(np.int32)
        np.maximum.at(
            image,
            (img_ys[inside], img_xs[inside]),
            vals[inside],
        )

    def _write_tiff(self, image, influence_name, udim):
        clipped = np.clip(image, 0.0, 1.0)
        as_u16 = np.ascontiguousarray((clipped * 65535.0 + 0.5).astype(np.uint16))

        filename = "{}.{:04d}.tif".format(influence_name, udim)
        path = os.path.join(self.output_dir, filename)

        out = oiio.ImageOutput.create(path)
        if out is None:
            raise RuntimeError("OpenImageIO could not create ImageOutput for: {}".format(path))
        spec = oiio.ImageSpec(self.resolution, self.resolution, 1, "uint16")
        spec.attribute("compression", "zip")
        if not out.open(path, spec):
            raise RuntimeError("OpenImageIO open failed: {}".format(out.geterror()))
        if not out.write_image(as_u16):
            raise RuntimeError("OpenImageIO write failed: {}".format(out.geterror()))
        out.close()
        print("[skin-weights] wrote {}".format(path))
