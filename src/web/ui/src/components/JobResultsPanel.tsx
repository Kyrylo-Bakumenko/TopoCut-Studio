import { useState } from 'react';
import {
  Typography,
  Image,
  Card,
  Row,
  Col,
  Button,
  Segmented,
  Empty,
  Spin,
  Slider,
  theme,
} from 'antd';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import LayerStackPreview from './LayerStackPreview';
import type { JobFile, JobConfigResponse } from '../types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

interface JobResultsPanelProps {
  jobId: string;
  isCompleted: boolean;
}

export default function JobResultsPanel({ jobId, isCompleted }: JobResultsPanelProps) {
  const [tileSize, setTileSize] = useState<number>(100);
  const [gapMm, setGapMm] = useState<number>(1.0);
  const [viewMode, setViewMode] = useState<'tiles' | '3d'>('tiles');
  const [activeLayerId, setActiveLayerId] = useState<string | null>(null);
  const previewHeight = 420;
  const sidePanelWidth = 260;
  const sidePanelMinWidth = 220;
  const sidePanelMaxWidth = 280;
  const panelGap = 16;
  const { token } = theme.useToken();

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

  if (isLoading) {
    return (
      <Spin tip="Loading files...">
        <div style={{ minHeight: 120 }} />
      </Spin>
    );
  }

  if (!jobFiles || jobFiles.length === 0) {
    return <Empty description="No files generated." />;
  }

  const nestedSheets = jobFiles.filter((f) => f.category === 'nested' && f.type === 'svg');
  const compositeSheets = jobFiles.filter(
    (f) => f.category === 'nested' && f.type === 'png' && f.name.includes('composite'),
  );
  const textures = jobFiles
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
      id: item.name,
      url: `${API_URL}${item.url}`,
      elevation: elev,
    };
  });

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
                  const isActive = activeLayerId === item.name;
                  const tileBorderColor = isActive ? token.colorPrimary : token.colorBorder;
                  return (
                    <div
                      key={item.url}
                      onMouseEnter={() => setActiveLayerId(item.name)}
                      onMouseLeave={() => setActiveLayerId(null)}
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

              <div style={{ display: 'flex', gap: panelGap, alignItems: 'stretch' }}>
                <div
                  style={{
                    minWidth: sidePanelMinWidth,
                    maxWidth: sidePanelMaxWidth,
                    flex: `0 0 ${sidePanelWidth}px`,
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <Typography.Text style={{ marginBottom: 8 }}>Layers</Typography.Text>
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                      height: previewHeight,
                      overflowY: 'auto',
                      paddingRight: 6,
                    }}
                  >
                    {textures.map((item, idx) => {
                      const elevMatch = item.name.match(/elev_(\d+)/);
                      const elev = elevMatch ? elevMatch[1] : '?';
                      const isActive = activeLayerId === item.name;
                      const tileBorderColor = isActive ? token.colorPrimary : token.colorBorder;
                      return (
                        <div
                          key={item.url}
                          onMouseEnter={() => setActiveLayerId(item.name)}
                          onMouseLeave={() => setActiveLayerId(null)}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                            padding: 6,
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
                </div>

                <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                  <Typography.Text style={{ marginBottom: 8 }}>3D Preview</Typography.Text>
                  <LayerStackPreview
                    layers={layerTextures}
                    widthIn={modelWidthIn}
                    heightIn={modelHeightIn}
                    thicknessMm={layerThicknessMm}
                    gapMm={gapMm}
                    activeLayerId={activeLayerId}
                    minHighlightGapMm={5}
                  />
                </div>
              </div>
            </div>
          )}
        </>
      )}



      {nestedSheets.length > 0 && (
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
                    <div
                      style={{
                        padding: 8,
                        background: '#fafafa',
                        display: 'flex',
                        justifyContent: 'center',
                      }}
                    >
                      <Image src={`${API_URL}${item.url}`} height={120} />
                    </div>
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

      {compositeSheets.length > 0 && (
        <>
          <Typography.Title level={5} style={{ marginTop: 16, marginBottom: 12 }}>
            Composite Sheets (Texture + Vector)
          </Typography.Title>
          <Row gutter={[12, 12]}>
            {compositeSheets.map((item) => (
              <Col key={item.url} xs={24} sm={12} md={12} lg={8} xl={6}>
                <Card
                  title={
                    <span style={{ fontSize: 12 }}>{item.name.replace('_composite.png', '')}</span>
                  }
                  size="small"
                  styles={{ body: { padding: 8 } }}
                  cover={
                    <div
                      style={{
                        padding: 8,
                        background: '#fafafa',
                        display: 'flex',
                        justifyContent: 'center',
                        alignItems: 'center',
                        height: 156,
                      }}
                    >
                      <Image
                        src={`${API_URL}${item.url}`}
                        width="100%"
                        height={140}
                        style={{ objectFit: 'contain' }}
                      />
                    </div>
                  }
                  actions={[
                    <Button type="link" size="small" href={`${API_URL}${item.url}`} target="_blank">
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
            ))}
          </Row>
        </>
      )}
    </div>
  );
}
