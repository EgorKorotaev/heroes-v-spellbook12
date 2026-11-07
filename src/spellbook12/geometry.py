"""Nival mesh container; preserves unmodified leaves byte for byte.

Format reference: senyaak/homm5-editor, docs/GEOMETRY_FORMAT.md.
"""
from dataclasses import dataclass
import copy
import struct
import math

CONTAINERS = {'/1', '/1/2', '/1/2/1', '/1/2/1/1'} | {
    f'/1/2/1/1/{n}' for n in range(2, 9)
}

@dataclass
class Record:
    tag: int
    value: bytes | list

    def child(self, tag):
        return next(r for r in self.value if r.tag == tag)

def decode(data, path=''):
    result = []
    at = 0
    while at < len(data):
        tag = data[at]
        size = data[at+1]
        width = 4 if size & 1 else 1
        if width == 4:
            size = struct.unpack_from('<I', data, at+1)[0]
        size //= 2
        start = at + 1 + width
        end = start + size
        if end > len(data):
            raise ValueError(f'Invalid record at {path}/{tag}: {end} > {len(data)}')
        body = data[start:end]
        child_path = f'{path}/{tag}'
        value = decode(body, child_path) if child_path in CONTAINERS else body
        result.append(Record(tag, value))
        at = end
    return result

def encode(records):
    out = bytearray()
    for r in records:
        body = encode(r.value) if isinstance(r.value, list) else r.value
        out.append(r.tag)
        out.extend(bytes([len(body)*2]) if len(body) <= 127 else struct.pack('<I', len(body)*2+1))
        out.extend(body)
    return bytes(out)

def meshes(records):
    root = next(r for r in records if r.tag == 1)
    return root.child(2)

def array(group, tag):
    return group.child(tag).child(2).value

def positions(group):
    return list(struct.iter_unpack('<3f', array(group, 2)))

def project_forward(group, eye, fraction):
    """Move a fixed control toward the native camera along each viewing ray.

    Perspective projection stays unchanged. Its native triangles become nearer
    than the expanded spell overlays, so picking returns the actual control and
    highlight object together. UVs, attributes and skin data stay byte-identical.
    """
    assert 0 < fraction < 1
    clone = copy.deepcopy(group)
    clone.child(2).child(2).value = b''.join(
        struct.pack('<3f', *(e + (v-e)*(1-fraction) for v,e in zip(p,eye)))
        for p in positions(group))
    return clone

def spell_anchor_coefficients(records, parts, canvas, icon, book_scale):
    """Project authored icon triangles into the vanilla camera's UI presets.

    Returns centre/half-size offsets relative to the viewport centre, scaled by
    min(render width, render height * 4/3). Fixed leaves avoid skinning bounds
    that can be unavailable while a turning-leaf counterpart is hidden.
    """
    groups=[g for m in meshes(records).value if m.tag==1 for g in m.value if g.tag==1]
    bounds=[icon[0]/canvas[0]*2048,icon[1]/canvas[0]*2048,
            icon[2]/canvas[1]*2048,icon[3]/canvas[1]*2048]
    inv_tan=1/math.tan(math.radians(25))
    forward_y,up_y=3/math.sqrt(58),7/math.sqrt(58)
    result=[]
    def clip(poly,axis,limit,above):
        out=[]
        if not poly:return out
        for a,c in zip(poly,poly[1:]+poly[:1]):
            ia=a[1][axis]>=limit if above else a[1][axis]<=limit
            ic=c[1][axis]>=limit if above else c[1][axis]<=limit
            if ia:out.append(a)
            if ia!=ic:
                t=(limit-a[1][axis])/(c[1][axis]-a[1][axis])
                out.append(tuple(tuple(x+(y-x)*t for x,y in zip(v,w)) for v,w in zip(a,c)))
        return out
    for part in parts:
        group=groups[part];pp=positions(group)
        remap=[p[0] for p in struct.iter_unpack('<H',array(group,5))]
        attrs=array(group,3)
        vertices=[(pp[p],struct.unpack_from('<2h',attrs,i*20)) for i,p in enumerate(remap)]
        projected=[]
        for tri in struct.iter_unpack('<3H',array(group,7)):
            poly=[vertices[i] for i in tri]
            for axis,limit,above in [(0,bounds[0],True),(0,bounds[1],False),
                                     (1,bounds[2],True),(1,bounds[3],False)]:
                poly=clip(poly,axis,limit,above)
            for (x,y,z),uv in poly:
                depth=forward_y*y-up_y*z+17+forward_y
                assert depth>0
                projected.append((.5*inv_tan*book_scale[0]*x/depth,
                                  -.5*inv_tan*book_scale[1]*(up_y*y+forward_y*z+up_y)/depth))
        assert projected
        lo=[min(p[a] for p in projected) for a in (0,1)]
        hi=[max(p[a] for p in projected) for a in (0,1)]
        result.append(((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,
                       (hi[0]-lo[0])/2,(hi[1]-lo[1])/2))
    return result

def lift_surface(group, distance):
    """Move a spell overlay outward along its dominant authored normal."""
    pp = positions(group)
    remap = [x[0] for x in struct.iter_unpack('<H', array(group,5))]
    normal = [0.0,0.0,0.0]
    for tri in struct.iter_unpack('<3H',array(group,7)):
        a,b,c = [pp[remap[i]] for i in tri]
        u = [b[i]-a[i] for i in range(3)]
        v = [c[i]-a[i] for i in range(3)]
        cross = (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        normal = [a+b for a,b in zip(normal,cross)]
    axis = max(range(3),key=lambda i:abs(normal[i]))
    assert abs(normal[axis]) > 1e-6
    offset = distance if normal[axis] > 0 else -distance
    clone = copy.deepcopy(group)
    clone.child(2).child(2).value = b''.join(
        struct.pack('<3f',*(value+(offset if i==axis else 0) for i,value in enumerate(p)))
        for p in pp)
    return clone

def split_columns(group):
    """Clip the authored surface into two columns, including its skin weights.

    Doubling U around each new center matches a 256-wide outliner to the
    original 512-wide outliner without reducing the icon's pixel scale.
    The book surface, V coordinates and triangle winding stay in place.
    """
    pp = positions(group)
    remap = [x[0] for x in struct.iter_unpack('<H', array(group, 5))]
    attrs, skin = array(group, 3), array(group, 4)
    vertices = []
    for i, pos_index in enumerate(remap):
        raw = attrs[i*20:(i+1)*20]
        uv = struct.unpack_from('<2h', raw)
        binding = skin[pos_index*24:(pos_index+1)*24]
        weights = struct.unpack_from('<4f', binding)
        bones = binding[20:24]
        vertices.append((pp[pos_index], uv, tuple(raw[4:]),
                         {bone:weight for bone,weight in zip(bones,weights) if weight > 0}))
    lo, hi = min(v[1][0] for v in vertices), max(v[1][0] for v in vertices)
    middle = (lo+hi)/2
    triangles = list(struct.iter_unpack('<3H', array(group, 7)))

    def mix(a,b,t):
        linear = lambda x,y: tuple(p+(q-p)*t for p,q in zip(x,y))
        weights = {bone:a[3].get(bone,0)*(1-t)+b[3].get(bone,0)*t for bone in a[3].keys()|b[3].keys()}
        return linear(a[0],b[0]), linear(a[1],b[1]), linear(a[2],b[2]), weights

    outputs = []
    for side in (0,1):
        center = ((lo+middle)/2, (middle+hi)/2)[side]
        out = []
        for triangle in triangles:
            polygon = [vertices[i] for i in triangle]
            clipped = []
            for a,b in zip(polygon,polygon[1:]+polygon[:1]):
                inside_a = a[1][0] <= middle if side == 0 else a[1][0] >= middle
                inside_b = b[1][0] <= middle if side == 0 else b[1][0] >= middle
                if inside_a: clipped.append(a)
                if inside_a != inside_b:
                    clipped.append(mix(a,b,(middle-a[1][0])/(b[1][0]-a[1][0])))
            for i in range(1,len(clipped)-1):
                out.extend((clipped[0],clipped[i],clipped[i+1]))
        pos_data, attr_data, skin_data = bytearray(), bytearray(), bytearray()
        twins, first = [], {}
        for i,(p,uv,tail,weights) in enumerate(out):
            packed = struct.pack('<3f',*p)
            pos_data.extend(packed)
            twins.append(first.setdefault(packed,i))
            u = round(2*(uv[0]-center)+1024)
            attr_data.extend(struct.pack('<2h',u,round(uv[1])))
            attr_data.extend(bytes(max(0,min(255,round(x))) for x in tail))
            strongest = sorted(weights.items(),key=lambda x:x[1],reverse=True)[:4]
            total = sum(w for b,w in strongest)
            bb = [b for b,w in strongest]
            ww = [w/total for b,w in strongest]
            bb += [bb[0]]*(4-len(bb)); ww += [0]*(4-len(ww))
            quant = [round(w*255) for w in ww]
            quant[0] += 255-sum(quant)
            skin_data.extend(struct.pack('<4f',*ww)+bytes(quant)+bytes(bb))
        clone = copy.deepcopy(group)
        def replace(tag,count,data):
            clone.child(tag).value = [Record(1,struct.pack('<I',count)),Record(2,bytes(data))]
        count = len(out)
        assert 0 < count < 65536 and count % 3 == 0
        sequential = struct.pack('<'+'H'*count,*range(count))
        replace(2,count,pos_data); replace(3,count,attr_data); replace(4,count,skin_data)
        replace(5,count,sequential)
        replace(6,count,struct.pack('<'+'H'*count,*twins))
        replace(7,count//3,sequential)
        clone.child(9).value = struct.pack('<I',count//3)
        outputs.append(clone)
    return outputs

def widen_label_uv(group, canvas_width, canvas_height, icon_bottom, text_top, text_width,
                   horizontal_scale=1.0, column=0):
    """Keep icon UVs, expose a wider text range below the icon.

    Split triangles at the empty icon/text gap before changing U coordinates.
    Positions remain on the authored surface, including interpolated skin data.
    Optional U scaling about the shared page-centre boundary pulls both columns
    inward and compensates a wider camera without moving skinned vertices.
    """
    pp = positions(group)
    remap = [x[0] for x in struct.iter_unpack('<H', array(group,5))]
    attrs, skin = array(group,3), array(group,4)
    vertices = []
    for i, pos_index in enumerate(remap):
        raw = attrs[i*20:(i+1)*20]
        binding = skin[pos_index*24:(pos_index+1)*24]
        weights = struct.unpack_from('<4f',binding)
        vertices.append((pp[pos_index],struct.unpack_from('<2h',raw),tuple(raw[4:]),
                         {b:w for b,w in zip(binding[20:24],weights) if w>0}))
    lo, hi = min(v[1][0] for v in vertices), max(v[1][0] for v in vertices)
    bottom, top = icon_bottom/canvas_height*2048, text_top/canvas_height*2048
    new_lo = (canvas_width-text_width)/(2*canvas_width)*2048
    new_hi = 2048-new_lo
    assert column in (0,1) and horizontal_scale > 0

    def mix(a,b,t):
        lerp=lambda x,y:tuple(p+(q-p)*t for p,q in zip(x,y))
        weights={bone:a[3].get(bone,0)*(1-t)+b[3].get(bone,0)*t for bone in a[3].keys()|b[3].keys()}
        return lerp(a[0],b[0]),lerp(a[1],b[1]),lerp(a[2],b[2]),weights

    def clip(poly,threshold,above):
        result=[]
        if not poly:return result
        for a,b in zip(poly,poly[1:]+poly[:1]):
            inside_a=a[1][1]>=threshold if above else a[1][1]<=threshold
            inside_b=b[1][1]>=threshold if above else b[1][1]<=threshold
            if inside_a:result.append(a)
            if inside_a != inside_b:
                result.append(mix(a,b,(threshold-a[1][1])/(b[1][1]-a[1][1])))
        return result

    out=[]
    for tri in struct.iter_unpack('<3H',array(group,7)):
        original=[vertices[i] for i in tri]
        for band in range(3):
            poly=original
            if band==0:poly=clip(poly,bottom,False)
            elif band==1:poly=clip(clip(poly,bottom,True),top,False)
            else:poly=clip(poly,top,True)
            for i in range(1,len(poly)-1):out.extend((poly[0],poly[i],poly[i+1]))
    pos_data,attr_data,skin_data=bytearray(),bytearray(),bytearray()
    first,twins={},[]
    for i,(p,uv,tail,weights) in enumerate(out):
        packed=struct.pack('<3f',*p);pos_data.extend(packed)
        twins.append(first.setdefault(packed,i))
        blend=max(0,min(1,(uv[1]-bottom)/(top-bottom)))
        widened=new_lo+(uv[0]-lo)*(new_hi-new_lo)/(hi-lo)
        u=uv[0]+(widened-uv[0])*blend
        anchor_icon,anchor_text = (hi,new_hi) if column==0 else (lo,new_lo)
        anchor=anchor_icon+(anchor_text-anchor_icon)*blend
        u=anchor+(u-anchor)*horizontal_scale
        attr_data.extend(struct.pack('<2h',round(u),round(uv[1])))
        attr_data.extend(bytes(max(0,min(255,round(x))) for x in tail))
        strongest=sorted(weights.items(),key=lambda x:x[1],reverse=True)[:4]
        total=sum(w for b,w in strongest)
        bb=[b for b,w in strongest];ww=[w/total for b,w in strongest]
        bb+=[bb[0]]*(4-len(bb));ww+=[0]*(4-len(ww))
        quant=[round(w*255) for w in ww];quant[0]+=255-sum(quant)
        skin_data.extend(struct.pack('<4f',*ww)+bytes(quant)+bytes(bb))
    clone=copy.deepcopy(group)
    def replace(tag,count,data):
        clone.child(tag).value=[Record(1,struct.pack('<I',count)),Record(2,bytes(data))]
    count=len(out)
    assert 0<count<65536 and count%3==0
    sequential=struct.pack('<'+'H'*count,*range(count))
    replace(2,count,pos_data);replace(3,count,attr_data);replace(4,count,skin_data)
    replace(5,count,sequential)
    replace(6,count,struct.pack('<'+'H'*count,*twins))
    replace(7,count//3,sequential)
    clone.child(9).value=struct.pack('<I',count//3)
    return clone



def _sheet_vertices(group):
    pp=positions(group);attrs=array(group,3);skin=array(group,4)
    remap=[x[0]for x in struct.iter_unpack('<H',array(group,5))]
    return [(pp[p],attrs[i*20:(i+1)*20],skin[p*24:(p+1)*24])for i,p in enumerate(remap)]

def _cross_yz(a,b,c):
    return (b[0][1]-a[0][1])*(c[0][2]-a[0][2])-(b[0][2]-a[0][2])*(c[0][1]-a[0][1])

def conform_paper(paper,overlays,half=.02):
    """Make paper under each spell follow the same triangles and skin bindings.

    Interpolating bind positions and weights independently changes a subdivided
    surface under skinning. Reusing the spell triangles for the paper interior
    keeps a depth gap throughout the native flip. UVs come from the original
    paper; its narrow margins are retained and stitched at the new edge points.
    """
    if not 0 < half < .04:raise ValueError('Paper must stay inside the spell overlays')
    if not overlays:raise ValueError('Spell surfaces are required')
    pv=_sheet_vertices(paper);pt=[[pv[i]for i in tri]for tri in struct.iter_unpack('<3H',array(paper,7))]
    faces={-1:[],1:[]}
    for tri in pt:faces[1 if _cross_yz(*tri)>0 else -1].append(tri)
    cache={}
    def sample(p,side):
        key=(p[1],p[2],side)
        if key in cache:return cache[key]
        y,z=p[1:];best=None
        for a,b,c in faces[side]:
            ay,az=a[0][1:];by,bz=b[0][1:];cy,cz=c[0][1:]
            den=(by-cy)*(az-cz)+(cz-bz)*(ay-cy)
            if abs(den)<1e-12:continue
            u=((by-cy)*(z-cz)+(cz-bz)*(y-cy))/den
            v=((cy-ay)*(z-cz)+(az-cz)*(y-cy))/den;w=1-u-v
            if min(u,v,w)<-1e-4:continue
            best=(a,b,c,u,v,w);break
        if best is None:raise ValueError(('No paper UV at overlay point',p,side))
        a,b,c,u,v,w=best
        uvs=[struct.unpack_from('<2h',x[1])for x in (a,b,c)]
        uv=[round(sum(k*t[j]for k,t in zip((u,v,w),uvs)))for j in (0,1)]
        tail=bytes(max(0,min(255,round(sum(k*x[1][j]for k,x in zip((u,v,w),(a,b,c))))))for j in range(4,20))
        cache[key]=struct.pack('<2h',*uv)+tail
        return cache[key]
    output=[];boundary={side:[]for side in faces};allz=[]
    for group in overlays:
        vv=_sheet_vertices(group)
        for indexes in struct.iter_unpack('<3H',array(group,7)):
            tri=[vv[i]for i in indexes];side=1 if _cross_yz(*tri)>0 else -1
            for p,attrs,skin in tri:
                item=((side*half,p[1],p[2]),sample(p,side),skin)
                output.append(item);boundary[side].append(item);allz.append(p[2])
    low,high=min(allz),max(allz)
    for side in boundary:
        points=[]
        for item in boundary[side]:
            p=item[0]
            if min(abs(p[2]-low),abs(p[2]-high))>.003:continue
            if not any(math.hypot(p[1]-q[0][1],p[2]-q[0][2])<3e-5 for q in points):points.append(item)
        boundary[side]=points
    margin_triangles=0
    for tri in pt:
        centre_z=sum(x[0][2]for x in tri)/3
        if low<centre_z<high:continue
        side=1 if _cross_yz(*tri)>0 else -1
        points=boundary[side]
        def vertex(v):
            p,attrs,skin=v
            for candidate in points:
                if math.hypot(p[1]-candidate[0][1],p[2]-candidate[0][2])<3e-5:return candidate
            return ((side*half,p[1],p[2]),attrs,skin)
        polygon=[]
        for a,b in zip(tri,tri[1:]+tri[:1]):
            av,bv=vertex(a),vertex(b);polygon.append(av)
            ay,az=av[0][1:];by,bz=bv[0][1:];dy,dz=by-ay,bz-az;length2=dy*dy+dz*dz
            inside=[]
            for p in points:
                y,z=p[0][1:];t=((y-ay)*dy+(z-az)*dz)/length2
                if 1e-5<t<1-1e-5 and math.hypot(y-ay-t*dy,z-az-t*dz)<3e-5:inside.append((t,p))
            polygon.extend(p for t,p in sorted(inside,key=lambda x:x[0]))
        anchor=max(range(len(polygon)),key=lambda i:min(abs(polygon[i][0][2]-low),abs(polygon[i][0][2]-high)))
        polygon=polygon[anchor:]+polygon[:anchor]
        for i in range(1,len(polygon)-1):
            t=[polygon[0],polygon[i],polygon[i+1]]
            if abs(_cross_yz(*t))<1e-9:continue
            assert _cross_yz(*t)*side>0
            output.extend(t);margin_triangles+=1
    pp=bytearray();aa=bytearray();ss=bytearray();twins=[];first={}
    for i,(p,attrs,skin)in enumerate(output):
        packed=struct.pack('<3f',*p);pp.extend(packed);aa.extend(attrs);ss.extend(skin);twins.append(first.setdefault(packed,i))
    count=len(output);assert 0<count<65536 and count%3==0
    sequential=struct.pack('<'+'H'*count,*range(count));clone=copy.deepcopy(paper)
    for tag,n,data in [(2,count,pp),(3,count,aa),(4,count,ss),(5,count,sequential),(6,count,struct.pack('<'+'H'*count,*twins)),(7,count//3,sequential)]:
        clone.child(tag).value=[Record(1,struct.pack('<I',n)),Record(2,bytes(data))]
    clone.child(9).value=struct.pack('<I',count//3)
    return clone,{'vertices':count,'triangles':count//3,'margin_triangles':margin_triangles,'boundary_points':{str(k):len(v)for k,v in boundary.items()},'uv_samples':len(cache)}
