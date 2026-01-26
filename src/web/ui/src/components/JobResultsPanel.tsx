import { useState, useMemo, useEffect, useRef } from 'react';
import {
  Typography,
  Image,
  Card,
  Row,
  Col,
  Button,
  Tabs,
  Segmented,
  Empty,
  Spin,
  Slider,
  Switch,
  Modal,
  theme,
} from 'antd';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { useTexture } from '@react-three/drei';
import LayerStackPreview from './LayerStackPreview';
import type { JobFile, JobConfigResponse, SheetManifest, SheetCutout } from '../types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

interface JobResultsPanelProps {
  jobId: string;
  isCompleted: boolean;
}

type SheetAssetData = {
  sheetId: string;
  compositeUrl?: string;
  nestedUrl?: string;
  manifest?: SheetManifest;
};

export default function JobResultsPanel({ jobId, isCompleted }: JobResultsPanelProps) {
  const [tileSize, setTileSize] = useState<number>(100);
  const [gapMm, setGapMm] = useState<number>(1.0);
  const [viewMode, setViewMode] = useState<'tiles' | '3d'>('tiles');
  const [hoveredLayerId, setHoveredLayerId] = useState<string | null>(null);
  const [pinnedLayerId, setPinnedLayerId] = useState<string | null>(null);
  const [showSheetLabels, setShowSheetLabels] = useState<boolean>(false);
  const [expandedSheetId, setExpandedSheetId] = useState<string | null>(null);
  const [expandedSheetView, setExpandedSheetView] = useState<'composite' | 'nested' | null>(null);
  const [expandedInspectEnabled, setExpandedInspectEnabled] = useState<boolean>(true);
  const [sidePanelTab, setSidePanelTab] = useState<'layers' | 'sheets'>('layers');
  const [sidePanelWidth, setSidePanelWidth] = useState<number>(440);
  const [expandedSheetTiles, setExpandedSheetTiles] = useState<Record<string, boolean>>({});
  const previewHeight = 480;
  const sidePanelMinWidth = 260;
  const sidePanelMaxWidth = 520;
  const rightPanelMinWidth = 320;
  const dragHandleWidth = 8;
  const panelGap = 16;
  const dragHandleMargin = Math.max(0, Math.round(panelGap / 2 - dragHandleWidth / 2));
  const sidePanelContentHeight = Math.max(200, previewHeight);
  const sheetTileSize = tileSize === 64 ? 100 : tileSize === 100 ? 140 : 180;
  const { token } = theme.useToken();
  const activeLayerId = pinnedLayerId ?? hoveredLayerId;
  const normalizeLayerId = (layerId: string) => layerId.replace(/\.png$/i, '');
  const normalizedActiveLayerId = activeLayerId ? normalizeLayerId(activeLayerId) : null;
  const panelRef = useRef<HTMLDivElement | null>(null);
  const isResizingRef = useRef(false);

  const { data: jobFiles, isLoading } = useQuery({
    queryKey: ['jobFiles', jobId],
    queryFn: async () => {
      const res = await axios.get(`${API_URL}/jobs/${jobId}/files`);
      return res.data.files as JobFile[];
    },
    enabled: isCompleted,
  });

  const { data: jobConfig } = useQuery({
    queryKey: ['jobConfig', jobId],
    queryFn: async () => {
      const res = await axios.get(`${API_URL}/jobs/${jobId}/config`);
      return res.data as JobConfigResponse;
    },
    enabled: isCompleted,
  });

  const manifestFiles = (jobFiles ?? []).filter(
    (f) => f.category === 'nested' && f.type === 'json',
  );

  const { data: sheetManifests } = useQuery({
    queryKey: ['sheetManifests', jobId],
    queryFn: async () => {
      const responses = await Promise.all(
        manifestFiles.map((file) => axios.get(`${API_URL}${file.url}`)),
      );
      return responses.map((res) => res.data as SheetManifest);
    },
    enabled: isCompleted && manifestFiles.length > 0,
  });

  const resolvedFiles = jobFiles ?? [];
  const nestedSheets = resolvedFiles.filter((f) => f.category === 'nested' && f.type === 'svg');
  const compositeSheets = resolvedFiles.filter(
    (f) => f.category === 'nested' && f.type === 'png' && f.name.includes('composite'),
  );
  const textures = resolvedFiles
    .filter((f) => f.category === 'textures' && f.type === 'png')
    .sort((a, b) => {
      const getElev = (name: string) => {
        const match = name.match(/elev_(\d+)/);
        return match ? parseInt(match[1]) : 0;
      };
      return getElev(a.name) - getElev(b.name);
    });

  const modelWidthIn = jobConfig?.config?.model?.width_inches ?? 5.0;
  const modelHeightIn = jobConfig?.config?.model?.height_inches ?? 5.0;
  const layerThicknessMm = jobConfig?.config?.model?.layer_thickness_mm ?? 3.175;
  const layerTextures = textures.map((item) => {
    const elevMatch = item.name.match(/elev_(\d+)/);
    const elev = elevMatch ? parseInt(elevMatch[1]) : 0;
    return {
      id: normalizeLayerId(item.name),
      url: `${API_URL}${item.url}`,
      elevation: elev,
    };
  });

  useEffect(() => {
    if (layerTextures.length === 0) return;
    layerTextures.forEach((layer) => {
      useTexture.preload(layer.url);
    });
  }, [layerTextures]);

  const sheetManifestMap = useMemo(() => {
    const map = new Map<string, SheetManifest>();
    (sheetManifests ?? []).forEach((manifest) => {
      map.set(manifest.sheet_id, manifest);
    });
    return map;
  }, [sheetManifests]);

  const sheetAssets = useMemo(() => {
    const map = new Map<string, SheetAssetData>();
    const ensure = (sheetId: string): SheetAssetData => {
      const existing = map.get(sheetId);
      if (existing) return existing;
      const created = { sheetId };
      map.set(sheetId, created);
      return created;
    };
    compositeSheets.forEach((sheet) => {
      const sheetId = sheet.name.replace('_composite.png', '');
      ensure(sheetId).compositeUrl = `${API_URL}${sheet.url}`;
    });
    nestedSheets.forEach((sheet) => {
      const sheetId = sheet.name.replace('.svg', '');
      ensure(sheetId).nestedUrl = `${API_URL}${sheet.url}`;
    });
    sheetManifestMap.forEach((manifest, sheetId) => {
      ensure(sheetId).manifest = manifest;
    });
    const parseSheetIndex = (sheetId: string) => {
      const match = sheetId.match(/sheet_(\d+)/);
      return match ? parseInt(match[1], 10) : Number.MAX_SAFE_INTEGER;
    };
    return Array.from(map.values()).sort(
      (a, b) => parseSheetIndex(a.sheetId) - parseSheetIndex(b.sheetId),
    );
  }, [compositeSheets, nestedSheets, sheetManifestMap]);

  useEffect(() => {
    if (expandedSheetId) {
      setExpandedInspectEnabled(true);
    }
  }, [expandedSheetId]);

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      if (!isResizingRef.current) return;
      const container = panelRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const maxFromContainer = rect.width - rightPanelMinWidth - dragHandleWidth;
      const maxAllowed = Math.max(
        sidePanelMinWidth,
        Math.min(sidePanelMaxWidth, maxFromContainer),
      );
      const nextWidth = Math.min(
        Math.max(event.clientX - rect.left, sidePanelMinWidth),
        maxAllowed,
      );
      setSidePanelWidth(nextWidth);
    };

    const handlePointerUp = () => {
      if (!isResizingRef.current) return;
      isResizingRef.current = false;
      document.body.style.cursor = '';
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      document.body.style.cursor = '';
    };
  }, [dragHandleWidth, rightPanelMinWidth, sidePanelMaxWidth, sidePanelMinWidth]);

  const buildRingPath = (ring: [number, number][], sheetHeight: number) =>
    ring
      .map((point, index) => {
        const x = point[0];
        const y = sheetHeight - point[1];
        return `${index === 0 ? 'M' : 'L'} ${x} ${y}`;
      })
      .join(' ') + ' Z';

  const buildPolygonPath = (polygon: SheetCutout['polygons'][number], sheetHeight: number) => {
    const paths = [buildRingPath(polygon.exterior, sheetHeight)];
    polygon.holes.forEach((hole) => {
      paths.push(buildRingPath(hole, sheetHeight));
    });
    return paths.join(' ');
  };

  const buildCutoutPath = (cutout: SheetCutout, sheetHeight: number) =>
    cutout.polygons.map((poly) => buildPolygonPath(poly, sheetHeight)).join(' ');

  const expandedSheet = useMemo(() => {
    if (!expandedSheetId) return null;
    return sheetAssets.find((sheet) => sheet.sheetId === expandedSheetId) ?? null;
  }, [expandedSheetId, sheetAssets]);
  const expandedSheetManifest = expandedSheet?.manifest ?? null;
  const expandedSheetImage =
    expandedSheetView === 'nested'
      ? expandedSheet?.nestedUrl ?? expandedSheet?.compositeUrl
      : expandedSheet?.compositeUrl ?? expandedSheet?.nestedUrl;
  const expandedSheetAspectRatio = expandedSheetManifest
    ? `${expandedSheetManifest.sheet_width_mm} / ${expandedSheetManifest.sheet_height_mm}`
    : '2 / 1';
  const expandedSheetTitle = expandedSheet
    ? `${expandedSheet.sheetId.replace('sheet_', 'Sheet ')}${
        expandedSheetView
          ? ` - ${expandedSheetView === 'nested' ? 'Nested' : 'Composite'}`
          : ''
      }`
    : '';

  const compositeSheetList = useMemo(
    () => sheetAssets.filter((sheet) => sheet.compositeUrl),
    [sheetAssets],
  );
  const nestedSheetList = useMemo(
    () => sheetAssets.filter((sheet) => sheet.nestedUrl),
    [sheetAssets],
  );

  const openSheet = (sheetId: string, view: 'composite' | 'nested') => {
    setExpandedSheetId(sheetId);
    setExpandedSheetView(view);
  };

  const sheetTileKey = (sheetId: string, view: 'composite' | 'nested') =>
    `${sheetId}:${view}`;

  const isSheetTileExpanded = (sheetId: string, view: 'composite' | 'nested') => {
    const key = sheetTileKey(sheetId, view);
    return expandedSheetTiles[key] ?? true;
  };

  const toggleSheetTileExpanded = (sheetId: string, view: 'composite' | 'nested') => {
    const key = sheetTileKey(sheetId, view);
    const currentlyExpanded = isSheetTileExpanded(sheetId, view);
    const nextExpanded = !currentlyExpanded;
    setExpandedSheetTiles((prev) => ({ ...prev, [key]: nextExpanded }));
    if (!nextExpanded) {
      setHoveredLayerId(null);
    }
  };

  const renderSheetTile = (sheet: SheetAssetData, view: 'composite' | 'nested') => {
    const imageUrl = view === 'composite' ? sheet.compositeUrl : sheet.nestedUrl;
    if (!imageUrl) return null;
    const isExpanded = isSheetTileExpanded(sheet.sheetId, view);
    const isActive = !!(
      normalizedActiveLayerId &&
      sheet.manifest?.cutouts.some(
        (cutout) => normalizeLayerId(cutout.layer_id) === normalizedActiveLayerId,
      )
    );
    const tileBorderColor = isActive ? token.colorPrimary : token.colorBorder;
    const aspectRatio = sheet.manifest
      ? `${sheet.manifest.sheet_width_mm} / ${sheet.manifest.sheet_height_mm}`
      : '2 / 1';
    const imageWrapperStyle = isExpanded
      ? {
          position: 'relative' as const,
          width: '100%',
          aspectRatio,
          borderRadius: 6,
          overflow: 'hidden',
        }
      : {
          position: 'relative' as const,
          width: sheetTileSize,
          height: sheetTileSize,
          borderRadius: 6,
          overflow: 'hidden',
          flex: '0 0 auto',
        };
    return (
      <div
        key={`${sheet.sheetId}-${view}`}
        onClick={() => {
          if (isExpanded) {
            openSheet(sheet.sheetId, view);
          }
        }}
        onMouseLeave={() => {
          if (isExpanded) {
            setHoveredLayerId(null);
          }
        }}
        style={{
          display: 'flex',
          flexDirection: isExpanded ? 'column' : 'row',
          alignItems: isExpanded ? 'stretch' : 'center',
          gap: 10,
          padding: 6,
          borderRadius: 8,
          border: `1px solid ${tileBorderColor}`,
          boxSizing: 'border-box',
          boxShadow: isActive ? `0 0 0 1px ${token.colorPrimary}` : 'none',
          background: token.colorBgContainer,
          transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
          cursor: isExpanded ? 'pointer' : 'default',
        }}
      >
        <div style={imageWrapperStyle}>
          <img
            src={imageUrl}
            alt={`${sheet.sheetId} ${view}`}
            style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
          />
          {isExpanded &&
            sheet.manifest &&
            renderSheetOverlay(sheet.manifest, {
              showLabels: showSheetLabels,
              fontSize: isExpanded ? 18 : 4,
              dimInactive: true,
            })}
          <Button
            type="text"
            size="small"
            onClick={(event) => {
              event.stopPropagation();
              toggleSheetTileExpanded(sheet.sheetId, view);
            }}
            style={{
              position: 'absolute',
              top: 4,
              right: 4,
              minWidth: 22,
              height: 22,
              padding: 0,
              lineHeight: '22px',
              borderRadius: 6,
              border: `1px solid ${token.colorBorder}`,
              background: token.colorBgContainer,
              zIndex: 2,
            }}
          >
            {isExpanded ? '-' : '+'}
          </Button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text style={{ fontSize: 12 }}>
            {sheet.sheetId.replace('sheet_', 'Sheet ')}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {view === 'composite' ? 'Composite' : 'Nested'}
          </Typography.Text>
        </div>
      </div>
    );
  };

  const renderSheetOverlay = (
    manifest: SheetManifest,
    options?: { showLabels?: boolean; fontSize?: number; dimInactive?: boolean },
  ) => {
    const sheetWidth = manifest.sheet_width_mm;
    const sheetHeight = manifest.sheet_height_mm;
    const arrowLength = Math.max(8, sheetWidth / 80);
    const arrowHead = arrowLength * 0.35;
    const fontSize = options?.fontSize ?? 6;
    const showLabels = options?.showLabels ?? false;
    const dimInactive = options?.dimInactive ?? false;

    return (
      <svg
        viewBox={`0 0 ${sheetWidth} ${sheetHeight}`}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
        }}
      >
        {manifest.cutouts.map((cutout) => {
          const cutoutLayerId = normalizeLayerId(cutout.layer_id);
          const isActive = normalizedActiveLayerId === cutoutLayerId;
          const strokeColor = isActive ? token.colorPrimary : token.colorTextSecondary;
          const fillColor = isActive ? token.colorPrimary : 'transparent';
          const fillOpacity = isActive ? 0.16 : 0;
          const labelX = cutout.label_point[0];
          const labelY = sheetHeight - cutout.label_point[1];
          const angleRad = (cutout.rotation_deg * Math.PI) / 180;
          const dirX = -Math.sin(angleRad);
          const dirY = -Math.cos(angleRad);
          const endX = labelX + dirX * arrowLength;
          const endY = labelY + dirY * arrowLength;
          const perpX = -dirY;
          const perpY = dirX;
          const leftX = endX - dirX * arrowHead + perpX * arrowHead;
          const leftY = endY - dirY * arrowHead + perpY * arrowHead;
          const rightX = endX - dirX * arrowHead - perpX * arrowHead;
          const rightY = endY - dirY * arrowHead - perpY * arrowHead;
          const labelVisible = showLabels || isActive;
          const inactiveOpacity = dimInactive && normalizedActiveLayerId && !isActive ? 0.2 : 1;
          return (
            <g key={cutout.id} opacity={inactiveOpacity}>
              <path
                d={buildCutoutPath(cutout, sheetHeight)}
                fill={fillColor}
                fillOpacity={fillOpacity}
                fillRule="evenodd"
                stroke={strokeColor}
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
                onMouseEnter={() => setHoveredLayerId(cutoutLayerId)}
                onMouseLeave={() => setHoveredLayerId(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  setPinnedLayerId((prev) =>
                    prev === cutoutLayerId ? null : cutoutLayerId,
                  );
                }}
                style={{ cursor: 'pointer' }}
              >
                <title>{`Layer ${cutout.layer_index + 1} • ${cutout.elevation_m}m`}</title>
              </path>
              <line
                x1={labelX}
                y1={labelY}
                x2={endX}
                y2={endY}
                stroke={strokeColor}
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
                opacity={isActive ? 0.9 : 0.5}
                pointerEvents="none"
              />
              <polygon
                points={`${endX},${endY} ${leftX},${leftY} ${rightX},${rightY}`}
                fill={strokeColor}
                opacity={isActive ? 0.9 : 0.5}
                pointerEvents="none"
              />
              {labelVisible && (
                <text
                  x={labelX}
                  y={labelY}
                  fill={strokeColor}
                  fontSize={fontSize}
                  textAnchor="middle"
                  dominantBaseline="central"
                  paintOrder="stroke"
                  stroke={token.colorBgContainer}
                  strokeWidth={1}
                  pointerEvents="none"
                >
                  {cutout.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    );
  };

  if (isLoading) {
    return (
      <Spin tip="Loading files...">
        <div style={{ minHeight: 120 }} />
      </Spin>
    );
  }

  if (resolvedFiles.length === 0) {
    return <Empty description="No files generated." />;
  }

  return (
    <div style={{ padding: '12px 0' }}>
      {textures.length > 0 && (
        <>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginBottom: 10,
              justifyContent: 'space-between',
            }}
          >
            <Typography.Title level={5} style={{ margin: 0 }}>
              Textures (Bottom → Top)
            </Typography.Title>
            <Segmented
              size="small"
              options={[
                { label: 'Tiles', value: 'tiles' },
                { label: '3D', value: '3d' },
              ]}
              value={viewMode}
              onChange={(val) => setViewMode(val as 'tiles' | '3d')}
            />
          </div>

          {viewMode === 'tiles' && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                <Typography.Text type="secondary">Tile size</Typography.Text>
                <Segmented
                  size="small"
                  options={[
                    { label: 'S', value: 64 },
                    { label: 'M', value: 100 },
                    { label: 'L', value: 140 },
                  ]}
                  value={tileSize}
                  onChange={(val) => setTileSize(val as number)}
                />
              </div>
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 12,
                  alignItems: 'flex-start',
                  maxHeight: 360,
                  overflowY: 'auto',
                  paddingRight: 6,
                }}
              >
                {textures.map((item, idx) => {
                  const elevMatch = item.name.match(/elev_(\d+)/);
                  const elev = elevMatch ? elevMatch[1] : '?';
                  const textureId = normalizeLayerId(item.name);
                  const isActive = normalizedActiveLayerId === textureId;
                  const tileBorderColor = isActive ? token.colorPrimary : token.colorBorder;
                  return (
                    <div
                      key={item.url}
                      onMouseEnter={() => setHoveredLayerId(textureId)}
                      onMouseLeave={() => setHoveredLayerId(null)}
                      onClick={() =>
                        setPinnedLayerId((prev) => (prev === textureId ? null : textureId))
                      }
                      style={{
                        width: tileSize + 28,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: 6,
                        padding: 8,
                        borderRadius: 8,
                        border: `1px solid ${tileBorderColor}`,
                        boxSizing: 'border-box',
                        boxShadow: isActive ? `0 0 0 1px ${token.colorPrimary}` : 'none',
                        background: token.colorBgContainer,
                        transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                        cursor: 'pointer',
                      }}
                    >
                      <Image
                        src={`${API_URL}${item.url}`}
                        width={tileSize}
                        height={tileSize}
                        style={{
                          objectFit: 'cover',
                          borderRadius: 6,
                          display: 'block',
                        }}
                        preview={{ mask: `Layer ${idx + 1}` }}
                      />
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <Typography.Text style={{ fontSize: 12 }}>Layer {idx + 1}</Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          {elev}m
                        </Typography.Text>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {viewMode === '3d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: panelGap,
                  flexWrap: 'wrap',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    flex: `0 0 ${sidePanelWidth}px`,
                    minWidth: sidePanelMinWidth,
                    maxWidth: sidePanelMaxWidth,
                  }}
                >
                  <Typography.Text type="secondary">Tile size</Typography.Text>
                  <Segmented
                    size="small"
                    options={[
                      { label: 'S', value: 64 },
                      { label: 'M', value: 100 },
                      { label: 'L', value: 140 },
                    ]}
                    value={tileSize}
                    onChange={(val) => setTileSize(val as number)}
                  />
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    flex: 1,
                    minWidth: 220,
                  }}
                >
                  <Typography.Text type="secondary">Layer gap (mm)</Typography.Text>
                  <Slider
                    min={0}
                    max={5}
                    step={0.5}
                    value={gapMm}
                    onChange={(val) => setGapMm(val as number)}
                    style={{ width: 180, maxWidth: '100%' }}
                  />
                </div>
              </div>

              <div
                ref={panelRef}
                style={{ display: 'flex', gap: 0, alignItems: 'flex-start' }}
              >
                <div
                  style={{
                    minWidth: sidePanelMinWidth,
                    maxWidth: sidePanelMaxWidth,
                    flex: `0 0 ${sidePanelWidth}px`,
                  }}
                >
                  <Tabs
                    size="small"
                    type="card"
                    activeKey={sidePanelTab}
                    onChange={(key) => setSidePanelTab(key as 'layers' | 'sheets')}
                    items={[
                      {
                        key: 'layers',
                        label: 'Layers',
                        children: (
                          <div
                            style={{
                              display: 'flex',
                              flexDirection: 'column',
                              gap: 8,
                              height: sidePanelContentHeight,
                              overflowY: 'auto',
                              paddingRight: 6,
                            }}
                          >
                            {textures.map((item, idx) => {
                              const elevMatch = item.name.match(/elev_(\d+)/);
                              const elev = elevMatch ? elevMatch[1] : '?';
                              const textureId = normalizeLayerId(item.name);
                              const isActive = normalizedActiveLayerId === textureId;
                              const tileBorderColor = isActive
                                ? token.colorPrimary
                                : token.colorBorder;
                              return (
                                <div
                                  key={item.url}
                                  onMouseEnter={() => setHoveredLayerId(textureId)}
                                  onMouseLeave={() => setHoveredLayerId(null)}
                                  onClick={() =>
                                    setPinnedLayerId((prev) =>
                                      prev === textureId ? null : textureId,
                                    )
                                  }
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 10,
                                    padding: 6,
                                    borderRadius: 8,
                                    border: `1px solid ${tileBorderColor}`,
                                    boxSizing: 'border-box',
                                    boxShadow: isActive
                                      ? `0 0 0 1px ${token.colorPrimary}`
                                      : 'none',
                                    background: token.colorBgContainer,
                                    transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                                    cursor: 'pointer',
                                  }}
                                >
                                  <Image
                                    src={`${API_URL}${item.url}`}
                                    width={tileSize}
                                    height={tileSize}
                                    style={{
                                      objectFit: 'cover',
                                      borderRadius: 6,
                                      display: 'block',
                                    }}
                                    preview={{ mask: `Layer ${idx + 1}` }}
                                  />
                                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <Typography.Text style={{ fontSize: 12 }}>
                                      Layer {idx + 1}
                                    </Typography.Text>
                                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                                      {elev}m
                                    </Typography.Text>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ),
                      },
                      {
                        key: 'sheets',
                        label: 'Sheets',
                        children: (
                          <div
                            style={{
                              display: 'flex',
                              flexDirection: 'column',
                              gap: 8,
                              height: sidePanelContentHeight,
                              overflowY: 'auto',
                              paddingRight: 6,
                            }}
                          >
                            {compositeSheetList.length === 0 && nestedSheetList.length === 0 && (
                              <Typography.Text
                                type="secondary"
                                style={{ fontSize: 12, padding: '6px 0' }}
                              >
                                No sheets yet.
                              </Typography.Text>
                            )}
                            {compositeSheetList.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  Composite
                                </Typography.Text>
                                {compositeSheetList.map((sheet) =>
                                  renderSheetTile(sheet, 'composite'),
                                )}
                              </div>
                            )}
                            {nestedSheetList.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  Nested
                                </Typography.Text>
                                {nestedSheetList.map((sheet) => renderSheetTile(sheet, 'nested'))}
                              </div>
                            )}
                          </div>
                        ),
                      },
                    ]}
                  />
                </div>
                <div
                  onPointerDown={(event) => {
                    event.preventDefault();
                    isResizingRef.current = true;
                    event.currentTarget.setPointerCapture(event.pointerId);
                    document.body.style.cursor = 'col-resize';
                  }}
                  style={{
                    width: dragHandleWidth,
                    margin: `0 ${dragHandleMargin}px`,
                    cursor: 'col-resize',
                    alignSelf: 'stretch',
                    borderRadius: 4,
                    background: token.colorBorder,
                  }}
                  role="separator"
                  aria-orientation="vertical"
                />
                <div
                  style={{
                    flex: 1,
                    minWidth: rightPanelMinWidth,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 12,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <Typography.Text>3D Preview</Typography.Text>
                  </div>
                  <LayerStackPreview
                    layers={layerTextures}
                    widthIn={modelWidthIn}
                    heightIn={modelHeightIn}
                    thicknessMm={layerThicknessMm}
                    gapMm={gapMm}
                    activeLayerId={normalizedActiveLayerId}
                    minHighlightGapMm={5}
                    heightPx={previewHeight}
                  />
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {viewMode === 'tiles' && nestedSheets.length > 0 && (
        <>
          <Typography.Title level={5} style={{ marginTop: 16, marginBottom: 12 }}>
            Nested Sheets (Vector)
          </Typography.Title>
          <Row gutter={[12, 12]}>
            {nestedSheets.map((item) => (
              <Col key={item.url} xs={24} sm={12} md={12} lg={8} xl={6}>
                <Card
                  title={<span style={{ fontSize: 12 }}>{item.name.replace('.svg', '')}</span>}
                  size="small"
                  styles={{ body: { padding: 8 } }}
                  cover={
                    <Image
                      src={`${API_URL}${item.url}`}
                      height={120}
                      preview={false}
                      style={{ width: '100%', objectFit: 'contain', cursor: 'pointer' }}
                      onClick={() => {
                        const sheetId = item.name.replace('.svg', '');
                        openSheet(sheetId, 'nested');
                      }}
                    />
                  }
                  actions={[
                    <Button
                      type="link"
                      size="small"
                      href={`${API_URL}${item.url.replace('.svg', '.dxf')}`}
                      target="_blank"
                    >
                      Download DXF
                    </Button>,
                  ]}
                />
              </Col>
            ))}
          </Row>
        </>
      )}

      {viewMode === 'tiles' && compositeSheets.length > 0 && (
        <>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginTop: 16,
              marginBottom: 12,
            }}
          >
            <Typography.Title level={5} style={{ margin: 0 }}>
              Composite Sheets (Texture + Vector)
            </Typography.Title>
          </div>
          <Row gutter={[12, 12]}>
            {compositeSheets.map((item) => {
              const sheetId = item.name.replace('_composite.png', '');
              return (
                <Col key={item.url} xs={24} sm={12} md={12} lg={8} xl={6}>
                  <Card
                    title={<span style={{ fontSize: 12 }}>{sheetId}</span>}
                    size="small"
                    styles={{ body: { padding: 8 } }}
                    cover={
                      <Image
                        src={`${API_URL}${item.url}`}
                        height={120}
                        preview={false}
                        style={{ width: '100%', objectFit: 'contain', cursor: 'pointer' }}
                        onClick={() => {
                          openSheet(sheetId, 'composite');
                        }}
                      />
                    }
                    actions={[
                      <Button
                        type="link"
                        size="small"
                        href={`${API_URL}${item.url}`}
                        target="_blank"
                      >
                        Download PNG
                      </Button>,
                      <Button
                        type="link"
                        size="small"
                        href={`${API_URL}${item.url.replace('_composite.png', '.dxf')}`}
                        target="_blank"
                      >
                        Download DXF
                      </Button>,
                    ]}
                  />
                </Col>
              );
            })}
          </Row>
        </>
      )}

      <Modal
        open={!!expandedSheet}
        onCancel={() => {
          setExpandedSheetId(null);
          setExpandedSheetView(null);
          setExpandedInspectEnabled(false);
        }}
        footer={null}
        width="80vw"
        title={expandedSheetTitle}
      >
        {expandedSheet && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {expandedSheetManifest && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                }}
              >
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {Math.round(expandedSheetManifest.sheet_width_mm)} ×{' '}
                  {Math.round(expandedSheetManifest.sheet_height_mm)} mm
                </Typography.Text>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Typography.Text type="secondary">Inspect</Typography.Text>
                    <Switch
                      size="small"
                      checked={expandedInspectEnabled}
                      onChange={setExpandedInspectEnabled}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Typography.Text type="secondary">Labels</Typography.Text>
                    <Switch
                      size="small"
                      checked={showSheetLabels}
                      onChange={setShowSheetLabels}
                      disabled={!expandedInspectEnabled}
                    />
                  </div>
                </div>
              </div>
            )}
            <div
              style={{
                position: 'relative',
                width: '100%',
                aspectRatio: expandedSheetAspectRatio,
                borderRadius: 10,
                overflow: 'hidden',
                border: `1px solid ${token.colorBorder}`,
                background: token.colorFillSecondary,
              }}
            >
              {expandedSheetImage ? (
                <img
                  src={expandedSheetImage}
                  alt={`${expandedSheet.sheetId} ${expandedSheetView ?? 'sheet'}`}
                  style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                />
              ) : (
                <Empty description="No preview available." />
              )}
              {expandedSheetManifest &&
                expandedInspectEnabled &&
                renderSheetOverlay(expandedSheetManifest, {
                  showLabels: showSheetLabels,
                  fontSize: 8,
                  dimInactive: true,
                })}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
