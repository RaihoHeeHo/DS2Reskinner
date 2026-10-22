import * as T from './vendor/three.module.min.js';

const $ = id => document.getElementById(id);
const notice = text => { $('notice').textContent = text; };
const scene = new T.Scene(); scene.background = new T.Color('#10151d');
const camera = new T.PerspectiveCamera(40, 1, .1, 100000);
let renderer;
try { renderer = new T.WebGLRenderer({canvas:$('canvas'), antialias:true}); }
catch (error) { notice(`WebGL is unavailable: ${error.message}`); throw error; }
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = T.SRGBColorSpace;
scene.add(new T.HemisphereLight(0xdcecff, 0x63626b, 2.2));
const light = new T.DirectionalLight(0xfff5e8, 2.3); light.position.set(2,4,5); scene.add(light);
const fill = new T.DirectionalLight(0xa6d5ff, 1.2); fill.position.set(-4,2,-3); scene.add(fill);
const group = new T.Group(); scene.add(group);
let grid = new T.GridHelper(200, 20, 0x506279, 0x263345); scene.add(grid);
const target = new T.Vector3();
let yaw = .25, pitch = .1, distance = 300, radius = 100;
let slotLabels = {};
let library = [], model = null, rendered = [], textures = [], matrices = [], boneLine = null;
let selectedDot = null, playing = false, frame = 0, lastTime = 0, loadVersion = 0;
const position = new T.Vector3(), scale = new T.Vector3(), quaternion = new T.Quaternion();
const scaleMatrix = new T.Matrix4(), local = new T.Matrix4(), otherQ = new T.Quaternion();

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function cameraUpdate() {
  camera.position.set(target.x + distance*Math.cos(pitch)*Math.sin(yaw),
    target.y + distance*Math.sin(pitch), target.z + distance*Math.cos(pitch)*Math.cos(yaw));
  camera.lookAt(target);
}
function disposeModel() {
  for (const object of [...group.children]) {
    group.remove(object); object.geometry?.dispose();
    if (object.material) object.material.dispose();
  }
  textures.forEach(t => t?.dispose()); textures=[]; rendered=[]; boneLine=null; selectedDot=null;
}
function fitCamera() {
  const box = new T.Box3();
  for (const item of rendered) { item.geometry.computeBoundingBox(); box.union(item.geometry.boundingBox); }
  if (box.isEmpty()) for (const matrix of matrices) {
    const e=matrix.elements; box.expandByPoint(new T.Vector3(e[12],-e[13],-e[14]));
  }
  box.getCenter(target);
  radius = Math.max(box.getSize(new T.Vector3()).length()/2, 1);
  distance = radius*3.2; yaw=.25; pitch=.1;
  camera.near=Math.max(.01,radius/1000); camera.far=radius*1000; camera.updateProjectionMatrix();
  scene.remove(grid); grid.geometry.dispose(); grid.material.dispose();
  grid=new T.GridHelper(radius*4,20,0x506279,0x263345); grid.position.y=box.min.y;
  grid.visible=$('grid').checked; scene.add(grid); cameraUpdate();
}
function buildModel(data) {
  disposeModel(); model=data; playing=false; frame=0; $('play').textContent='Play';
  $('title').textContent=data.name;
  const triangles=data.meshes.reduce((n,m)=>n+m.triangles.length,0);
  $('stats').textContent=`${data.nodes.length} bones · ${triangles.toLocaleString()} triangles · ${data.motions.filter(Boolean).length} animations · ${data.textures.length} textures`;
  matrices=data.nodes.map(()=>new T.Matrix4());
  textures=data.textures.map(t=> {
    if (!t) return null;
    const bytes=Uint8Array.from(atob(t.rgba),c=>c.charCodeAt(0));
    const tex=new T.DataTexture(bytes,t.width,t.height,T.RGBAFormat);
    tex.colorSpace=T.SRGBColorSpace; tex.magFilter=T.NearestFilter; tex.minFilter=T.LinearFilter;
    tex.wrapS=(t.wrap&15)===1?T.ClampToEdgeWrapping:T.RepeatWrapping;
    tex.wrapT=(t.wrap>>4)===1?T.ClampToEdgeWrapping:T.RepeatWrapping;
    tex.needsUpdate=true; return tex;
  });
  // Merge batches by material to keep draw calls small while retaining bone-local data.
  const groups=new Map();
  for (const batch of data.meshes) {
    if (!groups.has(batch.material)) groups.set(batch.material,[]);
    groups.get(batch.material).push(batch);
  }
  for (const [materialID,batches] of groups) {
    const count=batches.reduce((n,b)=>n+b.influences[0].positions.length,0);
    const vertices=new Float32Array(count*3), uv=new Float32Array(count*2), indices=[];
    let offset=0; const spans=[];
    for (const batch of batches) {
      const n=batch.influences[0].positions.length;
      for (let i=0;i<n;i++) {uv[(offset+i)*2]=batch.uv[i]?.[0]||0; uv[(offset+i)*2+1]=batch.uv[i]?.[1]||0;}
      for (const tri of batch.triangles) indices.push(...tri.map(i=>i+offset));
      spans.push({batch,offset,count:n}); offset+=n;
    }
    const geometry=new T.BufferGeometry();
    geometry.setAttribute('position',new T.BufferAttribute(vertices,3).setUsage(T.DynamicDrawUsage));
    geometry.setAttribute('uv',new T.BufferAttribute(uv,2)); geometry.setIndex(indices);
    const texture=textures[data.materials[materialID]?.texture] || null;
    const diffuse=data.materials[materialID]?.color;
    const tint=diffuse?new T.Color().setRGB(diffuse[0]/255,diffuse[1]/255,diffuse[2]/255,T.SRGBColorSpace):new T.Color(0xffffff);
    const material=new T.MeshStandardMaterial({map:$('textured').checked?texture:null,
      color:tint,side:T.DoubleSide,roughness:.85,metalness:0,alphaTest:.35,
      wireframe:$('wire').checked});
    const mesh=new T.Mesh(geometry,material); mesh.frustumCulled=false; group.add(mesh);
    rendered.push({geometry,vertices,spans,material,texture});
  }
  const lines=new Float32Array(data.nodes.filter(n=>n.parent>=0).length*6);
  const lineGeometry=new T.BufferGeometry(); lineGeometry.setAttribute('position',new T.BufferAttribute(lines,3));
  boneLine=new T.LineSegments(lineGeometry,new T.LineBasicMaterial({color:0x7ce3c0,depthTest:false}));
  boneLine.renderOrder=10; boneLine.visible=$('skeleton').checked; group.add(boneLine);
  selectedDot=new T.Mesh(new T.SphereGeometry(1,12,8),new T.MeshBasicMaterial({color:0xffce6c,depthTest:false}));
  selectedDot.visible=false; selectedDot.renderOrder=11; group.add(selectedDot);
  $('bones').replaceChildren(new Option('Highlight bone…','-1'));
  data.nodes.forEach((n,i)=>$('bones').add(new Option(`Bone ${i} · parent ${n.parent}`,String(i))));
  $('motion').value='-1'; labelMotions();
  $('motion').disabled=false; chooseMotion(); pose(); fitCamera();
  notice(data.warnings.join('\n'));
}
function labelMotions() {
  if (!model) return;
  const selected=$('motion').value;
  const game=$('labelGame').value==='auto'?model.game:$('labelGame').value;
  const labels=slotLabels[game]||{};
  $('motion').replaceChildren(new Option('Rest pose','-1'));
  model.motions.forEach((motion,i)=> {
    const info=model.motion_slots?.[i]||motion||{pack:0,slot:i};
    const name=labels[info.slot];
    const label=`${info.pack ? `Pack ${info.pack} · ` : ''}Slot ${info.slot}${name ? ` — ${name}` : ''} — ${motion?`${motion.frames} frames`:'empty'}`;
    const option=new Option(label,String(i));
    option.disabled=!motion; $('motion').add(option);
  });
  if ([...$('motion').options].some(o=>o.value===selected&&!o.disabled)) $('motion').value=selected;
}
$('labelGame').onchange=labelMotions;
function sample(track,time) {
  const times=track.times, values=track.values;
  if(time<=times[0])return values[0];
  if(time>=times.at(-1))return values.at(-1);
  let lo=0,hi=times.length-1;
  while(hi-lo>1){const mid=(lo+hi)>>1;if(times[mid]<=time)lo=mid;else hi=mid;}
  const t=(time-times[lo])/(times[hi]-times[lo]);
  if(track.type===3) {
    quaternion.fromArray(values[lo]).normalize(); otherQ.fromArray(values[hi]).normalize();
    quaternion.slerp(otherQ,t); return quaternion.toArray();
  }
  return values[lo].map((x,i)=>x+(values[hi][i]-x)*t);
}
function activeMotion() { return model?.motions[Number($('motion').value)]; }
function pose() {
  if(!model)return;
  const transforms=model.nodes.map(n=>({p:n.position,q:null,r:n.rotation,s:n.scale}));
  for(const track of activeMotion()?.tracks||[]) {
    const node=transforms[track.bone]; if(!node)continue;
    const value=sample(track,frame);
    if(track.type===0)node.p=value;
    if(track.type===2)node.s=value;
    if(track.type===3)node.q=value;
  }
  transforms.forEach((n,i)=> {
    position.fromArray(n.p); scale.fromArray(n.s);
    // MT00 rotations use the conjugate of the MD00/Three.js local rotation.
    if(n.q)quaternion.fromArray(n.q).normalize().conjugate();
    else quaternion.setFromEuler(new T.Euler(...n.r,'ZYX'));
    // DDS3 uses scale after rotation (row-vector convention in the PS2 tooling).
    local.makeRotationFromQuaternion(quaternion);
    local.premultiply(scaleMatrix.makeScale(scale.x,scale.y,scale.z)); local.setPosition(position);
    const parent=model.nodes[i].parent;
    if(parent>=0)matrices[i].multiplyMatrices(matrices[parent],local); else matrices[i].copy(local);
  });
  for(const item of rendered) {
    const out=item.vertices; out.fill(0);
    for(const {batch,offset,count} of item.spans) for(const inf of batch.influences) {
      const e=matrices[inf.bone].elements;
      for(let i=0;i<count;i++) {
        const [x,y,z,w]=inf.positions[i], j=(offset+i)*3;
        out[j]+=(e[0]*x+e[4]*y+e[8]*z+e[12])*w;
        out[j+1]-=(e[1]*x+e[5]*y+e[9]*z+e[13])*w;
        out[j+2]-=(e[2]*x+e[6]*y+e[10]*z+e[14])*w;
      }
    }
    item.geometry.attributes.position.needsUpdate=true; item.geometry.computeVertexNormals();
  }
  const lines=boneLine.geometry.attributes.position.array; let j=0;
  model.nodes.forEach((n,i)=> {if(n.parent<0)return;
    for(const id of [n.parent,i]) {const e=matrices[id].elements;lines[j++]=e[12];lines[j++]=-e[13];lines[j++]=-e[14];}
  });
  boneLine.geometry.attributes.position.needsUpdate=true;
  const selected=Number($('bones').value); selectedDot.visible=selected>=0;
  if(selected>=0){const e=matrices[selected].elements;selectedDot.position.set(e[12],-e[13],-e[14]);selectedDot.scale.setScalar(radius*.018);}
  $('frame').value=String(Math.round(frame));
  $('frameText').textContent=activeMotion()?`${Math.floor(frame)} / ${Math.max(0,activeMotion().frames-1)}`:'Rest pose';
}
function chooseMotion() {
  playing=false; frame=0; $('play').textContent='Play';
  const motion=activeMotion(), enabled=!!motion && motion.frames>0;
  for(const id of ['play','prev','next','frame'])$(id).disabled=!enabled;
  $('frame').max=String(Math.max(0,(motion?.frames||1)-1)); pose();
}
function filterLibrary() {
  const query=$('search').value.toLowerCase(), source=$('source').value;
  const matches=library.filter(m=>(!source||m.source===source)&&`${m.name} ${m.path}`.toLowerCase().includes(query));
  $('count').textContent=`${matches.length.toLocaleString()} files`;
  const fragment=document.createDocumentFragment();
  for(const info of matches) {
    const button=document.createElement('button');button.className='item';button.dataset.id=info.id;
    button.textContent=info.name || info.path.split('/').at(-1);
    const small=document.createElement('small');small.textContent=`${info.source} · ${info.path}`;button.append(small);
    button.onclick=()=>load(info,button);fragment.append(button);
  }
  $('library').replaceChildren(fragment);
}
async function load(info,button) {
  const version=++loadVersion;playing=false;$('play').textContent='Play';notice(`Loading ${info.name||info.path}…`);
  try {
    const data=await request(`./api/model?id=${info.id}`);if(version!==loadVersion)return;
    buildModel(data);document.querySelectorAll('.item.selected').forEach(b=>b.classList.remove('selected'));button.classList.add('selected');
  } catch(error) {if(version===loadVersion)notice(error.message);}
}
$('search').oninput=filterLibrary;$('source').onchange=filterLibrary;
$('motion').onchange=chooseMotion;
$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'Pause':'Play';};
$('frame').oninput=()=>{playing=false;$('play').textContent='Play';frame=Number($('frame').value);pose();};
function step(delta){playing=false;$('play').textContent='Play';frame=Math.max(0,Math.min(Number($('frame').max),Math.floor(frame)+delta));pose();}
$('prev').onclick=()=>step(-1);$('next').onclick=()=>step(1);
$('reset').onclick=()=>{if(model)fitCamera();};
$('wire').onchange=()=>rendered.forEach(x=>x.material.wireframe=$('wire').checked);
$('textured').onchange=()=>rendered.forEach(x=>{x.material.map=$('textured').checked?x.texture:null;x.material.needsUpdate=true;});
$('skeleton').onchange=()=>{if(boneLine)boneLine.visible=$('skeleton').checked;};
$('bones').onchange=pose;$('grid').onchange=()=>grid.visible=$('grid').checked;
$('open').onclick=()=>$('upload').click();
$('upload').onchange=async()=> {
  const file=$('upload').files[0];if(!file)return;
  if(file.size>32*1024*1024){notice('Choose a file smaller than 32 MB.');return;}
  const version=++loadVersion;playing=false;$('play').textContent='Play';notice(`Loading ${file.name}…`);
  try {const data=await request('./api/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    if(version===loadVersion){data.name=file.name;buildModel(data);}}
  catch(error){if(version===loadVersion)notice(error.message);}finally{$('upload').value='';}
};
let drag=null;
$('canvas').onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,button:e.button};$('canvas').setPointerCapture(e.pointerId);};
$('canvas').onpointermove=e=> {
  if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
  if(drag.button===2||e.shiftKey){const right=new T.Vector3().setFromMatrixColumn(camera.matrixWorld,0);
    const up=new T.Vector3().setFromMatrixColumn(camera.matrixWorld,1);target.addScaledVector(right,-dx*distance*.001).addScaledVector(up,dy*distance*.001);}
  else{yaw-=dx*.008;pitch=Math.max(-1.5,Math.min(1.5,pitch+dy*.008));}cameraUpdate();
};
$('canvas').onpointerup=$('canvas').onpointercancel=()=>drag=null;
$('canvas').oncontextmenu=e=>e.preventDefault();
$('canvas').addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(radius*.1,Math.min(radius*100,distance*Math.exp(e.deltaY*.001)));cameraUpdate();},{passive:false});
new ResizeObserver(entries=> {const {width,height}=entries[0].contentRect;
  renderer.setSize(width,height,false);camera.aspect=width/Math.max(1,height);camera.updateProjectionMatrix();}).observe($('viewport'));
function tick(time) {
  const dt=Math.min((time-lastTime)/1000,.1);lastTime=time;
  if(playing&&activeMotion()) {
    frame+=dt*Number($('fps').value)*Number($('speed').value);
    if(frame>=activeMotion().frames) {
      if($('loop').checked)frame%=Math.max(1,activeMotion().frames);
      else{frame=Math.max(0,activeMotion().frames-1);playing=false;$('play').textContent='Play';}
    }
    pose();
  }
  renderer.render(scene,camera);requestAnimationFrame(tick);
}
cameraUpdate();requestAnimationFrame(tick);
try {
  slotLabels=await request('./api/slot-labels');
  library=await request('./api/library');
  for(const source of new Set(library.map(m=>m.source)))$('source').add(new Option(source,source));
  filterLibrary();
} catch(error){notice(error.message);}
