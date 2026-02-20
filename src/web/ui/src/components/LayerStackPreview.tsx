import { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, useTexture, Center, Bounds } from '@react-three/drei';
import * as THREE from 'three';

interface LayerTexture {
  id: string;
  url: string;
  elevation: number;
}

interface LayerStackPreviewProps {
  layers: LayerTexture[];
  widthIn: number;
  heightIn: number;
  thicknessMm: number;
  gapMm: number;
  activeLayerId?: string | null;
  minHighlightGapMm?: number;
  heightPx?: number;
}

type MaskTextures = {
  alphaTexture: THREE.CanvasTexture | null;
  outlineTexture: THREE.CanvasTexture | null;
};

function buildMaskTextures(image: HTMLImageElement): MaskTextures {
  const canvas = document.createElement('canvas');
  const width = image.width;
  const height = image.height;
  if (width === 0 || height === 0) {
    return { alphaTexture: null, outlineTexture: null };
  }
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return { alphaTexture: null, outlineTexture: null };
  }
  ctx.drawImage(image, 0, 0);
  const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imgData.data;
  const w = canvas.width;
  const h = canvas.height;
  const visited = new Uint8Array(w * h);
  const queue: number[] = [];

  const isWhite = (idx: number) => {
    const r = data[idx];
    const g = data[idx + 1];
    const b = data[idx + 2];
    const a = data[idx + 3];
    return a < 10 || (r >= 250 && g >= 250 && b >= 250);
  };

  const pushIfWhite = (x: number, y: number) => {
    const i = y * w + x;
    if (visited[i]) return;
    const idx = i * 4;
    if (!isWhite(idx)) return;
    visited[i] = 1;
    queue.push(i);
  };

  for (let x = 0; x < w; x += 1) {
    pushIfWhite(x, 0);
    pushIfWhite(x, h - 1);
  }
  for (let y = 0; y < h; y += 1) {
    pushIfWhite(0, y);
    pushIfWhite(w - 1, y);
  }

  while (queue.length > 0) {
    const i = queue.pop() as number;
    const x = i % w;
    const y = Math.floor(i / w);
    if (x > 0) pushIfWhite(x - 1, y);
    if (x < w - 1) pushIfWhite(x + 1, y);
    if (y > 0) pushIfWhite(x, y - 1);
    if (y < h - 1) pushIfWhite(x, y + 1);
  }

  const alphaCanvas = document.createElement('canvas');
  alphaCanvas.width = w;
  alphaCanvas.height = h;
  const alphaCtx = alphaCanvas.getContext('2d');
  if (!alphaCtx) {
    return { alphaTexture: null, outlineTexture: null };
  }
  const alphaData = alphaCtx.createImageData(w, h);
  const out = alphaData.data;
  for (let i = 0; i < w * h; i += 1) {
    const alpha = visited[i] ? 0 : 255;
    const j = i * 4;
    out[j] = alpha;
    out[j + 1] = alpha;
    out[j + 2] = alpha;
    out[j + 3] = 255;
  }
  alphaCtx.putImageData(alphaData, 0, 0);
  const alphaTexture = new THREE.CanvasTexture(alphaCanvas);
  alphaTexture.wrapS = THREE.ClampToEdgeWrapping;
  alphaTexture.wrapT = THREE.ClampToEdgeWrapping;
  alphaTexture.needsUpdate = true;

  const outlineCanvas = document.createElement('canvas');
  outlineCanvas.width = w;
  outlineCanvas.height = h;
  const outlineCtx = outlineCanvas.getContext('2d');
  if (!outlineCtx) {
    return { alphaTexture, outlineTexture: null };
  }
  const outlineData = outlineCtx.createImageData(w, h);
  const outlineOut = outlineData.data;
  const edgeMask = new Uint8Array(w * h);

  const isBackground = (x: number, y: number) => {
    if (x < 0 || x >= w || y < 0 || y >= h) return true;
    return visited[y * w + x] === 1;
  };

  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const idx = y * w + x;
      if (visited[idx]) continue;
      const hasBackgroundNeighbor =
        isBackground(x - 1, y) ||
        isBackground(x + 1, y) ||
        isBackground(x, y - 1) ||
        isBackground(x, y + 1) ||
        isBackground(x - 1, y - 1) ||
        isBackground(x + 1, y - 1) ||
        isBackground(x - 1, y + 1) ||
        isBackground(x + 1, y + 1);
      if (hasBackgroundNeighbor) {
        edgeMask[idx] = 1;
      }
    }
  }

  const outlineRadius = 1;
  const expandedMask = new Uint8Array(w * h);

  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const idx = y * w + x;
      if (!edgeMask[idx]) continue;
      for (let dy = -outlineRadius; dy <= outlineRadius; dy += 1) {
        const ny = y + dy;
        if (ny < 0 || ny >= h) continue;
        for (let dx = -outlineRadius; dx <= outlineRadius; dx += 1) {
          const nx = x + dx;
          if (nx < 0 || nx >= w) continue;
          expandedMask[ny * w + nx] = 1;
        }
      }
    }
  }

  for (let i = 0; i < w * h; i += 1) {
    const j = i * 4;
    if (expandedMask[i]) {
      outlineOut[j] = 255;
      outlineOut[j + 1] = 255;
      outlineOut[j + 2] = 255;
      outlineOut[j + 3] = 255;
    } else {
      outlineOut[j] = 0;
      outlineOut[j + 1] = 0;
      outlineOut[j + 2] = 0;
      outlineOut[j + 3] = 0;
    }
  }

  outlineCtx.putImageData(outlineData, 0, 0);
  const outlineTexture = new THREE.CanvasTexture(outlineCanvas);
  outlineTexture.wrapS = THREE.ClampToEdgeWrapping;
  outlineTexture.wrapT = THREE.ClampToEdgeWrapping;
  outlineTexture.colorSpace = THREE.SRGBColorSpace;
  outlineTexture.minFilter = THREE.NearestFilter;
  outlineTexture.magFilter = THREE.NearestFilter;
  outlineTexture.generateMipmaps = false;
  outlineTexture.needsUpdate = true;

  return { alphaTexture, outlineTexture };
}

function LayerMesh({
  textureUrl,
  widthIn,
  heightIn,
  y,
  thicknessIn,
  isActive,
}: {
  textureUrl: string;
  widthIn: number;
  heightIn: number;
  y: number;
  thicknessIn: number;
  isActive: boolean;
}) {
  const texture = useTexture(textureUrl);
  const { alphaTexture, outlineTexture } = useMemo(() => {
    if (!texture.image) return { alphaTexture: null, outlineTexture: null };
    return buildMaskTextures(texture.image as HTMLImageElement);
  }, [texture.image]);

  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;

  const materials = useMemo(() => {
    const topMaterial = new THREE.MeshStandardMaterial({
      map: texture,
      alphaMap: alphaTexture ?? undefined,
      transparent: true,
      alphaTest: 0.5,
      color: new THREE.Color('#cbd5f5'),
      emissive: isActive ? new THREE.Color('#60a5fa') : new THREE.Color('#000000'),
      emissiveIntensity: isActive ? 0.5 : 0,
      roughness: 0.9,
      metalness: 0,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    });

    const sideMaterial = new THREE.MeshStandardMaterial({
      color: new THREE.Color(isActive ? '#1e293b' : '#0f172a'),
      roughness: 0.9,
      metalness: 0.05,
      side: THREE.FrontSide,
    });

    const bottomMaterial = new THREE.MeshStandardMaterial({
      color: new THREE.Color('#0b1220'),
      roughness: 0.95,
      metalness: 0.02,
      side: THREE.FrontSide,
    });

    return [
      sideMaterial,
      sideMaterial,
      topMaterial,
      bottomMaterial,
      sideMaterial,
      sideMaterial,
    ];
  }, [texture, alphaTexture, isActive]);

  const outlineColor = isActive ? '#60a5fa' : '#e2e8f0';
  const outlineOpacity = isActive ? 0.95 : 0.75;
  const outlineOffset = Math.max(0.0002, thicknessIn * 0.01);

  return (
    <mesh position={[0, y + thicknessIn / 2, 0]}>
      <boxGeometry args={[widthIn, thicknessIn, heightIn]} />
      {materials.map((material, index) => (
        <primitive key={index} object={material} attach={`material-${index}`} />
      ))}
      {outlineTexture && (
        <mesh
          position={[0, thicknessIn / 2 + outlineOffset, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <planeGeometry args={[widthIn, heightIn]} />
          <meshBasicMaterial
            map={outlineTexture}
            color={outlineColor}
            opacity={outlineOpacity}
            transparent
            depthWrite={false}
            toneMapped={false}
            polygonOffset
            polygonOffsetFactor={-1}
            polygonOffsetUnits={-1}
          />
        </mesh>
      )}
    </mesh>
  );
}

export default function LayerStackPreview({
  layers,
  widthIn,
  heightIn,
  thicknessMm,
  gapMm,
  activeLayerId = null,
  minHighlightGapMm = 5,
  heightPx = 420,
}: LayerStackPreviewProps) {
  const thicknessIn = thicknessMm / 25.4;
  const gapIn = Math.max(0, gapMm) / 25.4;
  const minHighlightGapIn = Math.max(0, minHighlightGapMm) / 25.4;
  const activeIndex = layers.findIndex((layer) => layer.id === activeLayerId);
  const gapSizes = layers.length > 1 ? new Array(layers.length - 1).fill(gapIn) : [];
  if (activeIndex >= 0 && layers.length > 1) {
    if (activeIndex > 0) {
      gapSizes[activeIndex - 1] = Math.max(gapSizes[activeIndex - 1], minHighlightGapIn);
    }
    if (activeIndex < gapSizes.length) {
      gapSizes[activeIndex] = Math.max(gapSizes[activeIndex], minHighlightGapIn);
    }
  }
  const stackHeight = layers.length * thicknessIn + gapSizes.reduce((sum, gap) => sum + gap, 0);
  const startY = -stackHeight / 2;
  const layerPositions = layers.map((_, idx) => {
    const gapsBefore = gapSizes.slice(0, idx).reduce((sum, gap) => sum + gap, 0);
    return startY + idx * thicknessIn + gapsBefore;
  });

  return (
    <div style={{ height: heightPx, width: '100%', background: '#0f172a', borderRadius: 8 }}>
      <Canvas camera={{ position: [0, 3, 6], fov: 45, near: 0.01, far: 100 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[5, 8, 5]} intensity={0.8} />
        <OrbitControls enablePan enableZoom enableRotate minDistance={1} maxDistance={12} />
        <Bounds fit clip observe>
          <Center>
            {layers.map((layer, idx) => (
              <LayerMesh
                key={layer.id}
                textureUrl={layer.url}
                widthIn={widthIn}
                heightIn={heightIn}
                thicknessIn={thicknessIn}
                y={layerPositions[idx]}
                isActive={layer.id === activeLayerId}
              />
            ))}
          </Center>
        </Bounds>
      </Canvas>
    </div>
  );
}
