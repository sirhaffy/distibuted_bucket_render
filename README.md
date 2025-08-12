This is an experiment or MVP to see if it’s possible to replicate Team Render in Blender using the power of Azure. The aim is to later develop this to work with Kubernetes.

## USP  
- Bucket rendering – send live feedback to the render view as each bucket is completed, just like Team Render does.
- Fast feedback on changes – see results instantly in the render view. This will help maintain creativity. Possibly add render region, but keep the rest of the frame visible.
- High-resolution rendering – test render in HD locally, but render in 16K on Azure.
- Send off a render job and continue working on other tasks in the meantime.

  
## To Do
- Check why it says:
  - "Rendering preview assembly..."
  - "Rendering EXR assembly..."
  - It’s not actually rendering, is it?

- Reorganize the panel (UI) so it’s more logical.

- It should send results back to the render view while rendering, for example every 25%, to give quick feedback. That’s the whole point.
