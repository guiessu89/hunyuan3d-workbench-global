# Studio compatibility

China observations are historical results documented in [VALIDATION.md](VALIDATION.md). Global fixtures test the adapter against simulated forms and assets.

| Workflow | China | Global implementation | Global live validation |
| --- | --- | --- | --- |
| Sign-in | Dedicated persistent Chrome profile | Dedicated profile and login guard | Signed-out redirect observed. Worker persistence pending. |
| Single-image geometry | Upstream form | Experimental. Offline upload, quota gate, submit, monitor and download tested. | Preparation blocked by sign-in. Generation and download pending. |
| Multiview geometry | Upstream verified generation and export | Experimental. Offline named uploads tested. | Preparation blocked by sign-in. Generation and download pending. |
| Text-to-3D | No verified geometry adapter | Support unconfirmed | Pending investigation |
| Concept and concept multiview | Upstream forms | No adapter | Pending investigation |
| Texture and multiview texture | Upstream forms. Multiview generation and GLB verified. | Texture Painting named by site. No adapter. | Pending investigation |
| Retopology and low-poly | Upstream form | Retopology named by site. No adapter. | Pending investigation |
| UV, components, rigging and animation | Upstream forms | No adapters | Pending investigation |
| Models and face count | Upstream presets | English face-count fixture. Uses site's default model. | Pending |
| Exports | Menu formats vary by asset | Prefers offered GLB, then FBX or STL for geometry. GLB fixture tested. | Existing asset export and actual available formats pending. |
| Blender and Unity | Local inspection and Blender script | Shared archive, file inspection and Blender script. Manual Unity handoff. | Native imports pending. |
