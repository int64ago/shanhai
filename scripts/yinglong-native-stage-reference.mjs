// Runs inside the real Stage page. Match geometry-only source masks by rest
// position; compression can reorder vertices, so source indices are never reused.
export function installNativeReference(reference) {
  const q = window.yinglongQA, T = q.T
  if (reference.sourceSha256 !== 'ac09ad235ef121212c695c54d8593234212df4d5a93818df113ff8002ab9eb00') throw new Error('Unexpected native source')
  const points = reference.points.map(([x,y,z]) => [x,z,-y]), cell = .001
  const key = (x,y,z) => `${x},${y},${z}`
  const grid = new Map()
  for (let i=0;i<points.length;i++) {
    const k=key(...points[i].map(v=>Math.floor(v/cell)))
    if (!grid.has(k)) grid.set(k,[])
    grid.get(k).push(i)
  }
  const sourceMeshes=[]
  q.source.updateMatrixWorld(true)
  q.source.traverse(n=>{if(n.isSkinnedMesh)sourceMeshes.push(n)})
  if(sourceMeshes.length!==1)throw new Error('Expected one native skinned surface')
  const source=sourceMeshes[0], count=source.geometry.attributes.position.count
  source.skeleton.update()
  const nativeIndex=[], rest=[], p=new T.Vector3()
  let maximumRestError=0
  for(let i=0;i<count;i++){
    source.getVertexPosition(i,p);source.localToWorld(p)
    const xyz=p.toArray(), c=xyz.map(v=>Math.floor(v/cell))
    let best=-1,error=Infinity
    for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(let dz=-1;dz<=1;dz++){
      for(const j of grid.get(key(c[0]+dx,c[1]+dy,c[2]+dz))??[]){
        const e=Math.hypot(...xyz.map((v,k)=>v-points[j][k]))
        if(e<error){error=e;best=j}
      }
    }
    if(best<0||error>.00025)throw new Error(`Unmatched compressed rest vertex ${i}: ${error}m`)
    maximumRestError=Math.max(maximumRestError,error);nativeIndex.push(best);rest.push(xyz)
  }
  const masks={}
  for(const [name,indices] of Object.entries(reference.masks)){
    const set=new Set(indices)
    masks[name]=nativeIndex.flatMap((id,i)=>set.has(id)?[i]:[])
    if(!masks[name].length)throw new Error(`Missing native mask ${name}`)
  }
  const sample=(ids,n)=>Array.from({length:Math.min(n,ids.length)},(_,i)=>ids[Math.floor(i*ids.length/Math.min(n,ids.length))])
  const pair=(a,b)=>({a,b,d:Math.hypot(...rest[a].map((v,k)=>v-rest[b][k]))})
  const protectedPairs={}, rootPairs={}
  for(const name of ['head','wing_tip_l','wing_tip_r',...Object.keys(masks).filter(n=>n.startsWith('feather_'))]){
    const ids=sample(masks[name],24), pairs=[]
    for(let i=0;i<ids.length;i++)for(let j=i+1;j<ids.length;j++)pairs.push(pair(ids[i],ids[j]))
    protectedPairs[name]=pairs
  }
  const index=source.geometry.index
  for(const name of ['wing_root_l','wing_root_r']){
    const set=new Set(masks[name]), edges=new Map()
    for(let i=0;i<index.count;i+=3){
      const ids=[index.getX(i),index.getX(i+1),index.getX(i+2)]
      for(let k=0;k<3;k++){
        const a=Math.min(ids[k],ids[(k+1)%3]),b=Math.max(ids[k],ids[(k+1)%3])
        if(set.has(a)&&set.has(b)){
          const edge=pair(a,b)
          if(edge.d>=.005)edges.set(`${a},${b}`,edge)
        }
      }
    }
    const all=[...edges.values()]
    rootPairs[name]=sample(all,300)
    if(!rootPairs[name].length)throw new Error(`Missing root edges ${name}`)
  }
  q.nativeMetrics=()=>{
    const mesh=q.meshes()[0], positions=new Map()
    const at=i=>{
      if(!positions.has(i)){
        mesh.getVertexPosition(i,p);mesh.localToWorld(p);positions.set(i,p.toArray())
      }
      return positions.get(i)
    }
    const distance=edge=>Math.hypot(...at(edge.a).map((v,k)=>v-at(edge.b)[k]))
    const rigidDistanceDrift={}, rootEdgeStrain={}
    for(const [name,pairs]of Object.entries(protectedPairs))rigidDistanceDrift[name]=Math.max(...pairs.map(e=>Math.abs(distance(e)-e.d)))
    for(const [name,pairs]of Object.entries(rootPairs))rootEdgeStrain[name]=Math.max(...pairs.map(e=>Math.abs(distance(e)/e.d-1)))
    return{rigidDistanceDrift,rootEdgeStrain}
  }
  return{sourceSha256:reference.sourceSha256,matchedCompressedVertices:count,maximumRestError,maskCounts:Object.fromEntries(Object.entries(masks).map(([k,v])=>[k,v.length])),protectedPairCounts:Object.fromEntries(Object.entries(protectedPairs).map(([k,v])=>[k,v.length])),rootEdgeCounts:Object.fromEntries(Object.entries(rootPairs).map(([k,v])=>[k,v.length]))}
}
