import { useState } from 'react';
import { Typography, Image, Card, Row, Col, Button, Segmented, Empty, Spin } from 'antd';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import type { JobFile } from '../types';

const API_URL = 'http://localhost:8000';

interface JobResultsPanelProps {
  jobId: string;
  isCompleted: boolean;
}

export default function JobResultsPanel({ jobId, isCompleted }: JobResultsPanelProps) {
  const [tileSize, setTileSize] = useState<number>(100);

  const { data: jobFiles, isLoading } = useQuery({
    queryKey: ['jobFiles', jobId],
    queryFn: async () => {
      const res = await axios.get(`${API_URL}/jobs/${jobId}/files`);
      return res.data.files as JobFile[];
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

  return (
    <div style={{ padding: '12px 0' }}>
      {textures.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
            <Typography.Title level={5} style={{ margin: 0 }}>
              Textures (Bottom → Top)
            </Typography.Title>
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
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {textures.map((item, idx) => {
              const elevMatch = item.name.match(/elev_(\d+)/);
              const elev = elevMatch ? elevMatch[1] : '?';
              return (
                <div key={item.url} style={{ textAlign: 'center', width: tileSize + 8 }}>
                  <Image
                    src={`${API_URL}${item.url}`}
                    width={tileSize}
                    height={tileSize}
                    style={{
                      objectFit: 'cover',
                      borderRadius: 4,
                      border: '1px solid #d9d9d9',
                    }}
                    preview={{ mask: `Layer ${idx + 1}` }}
                  />
                  <div style={{ fontSize: 10, color: '#666', marginTop: 2 }}>{elev}m</div>
                </div>
              );
            })}
          </div>
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
                      }}
                    >
                      <Image src={`${API_URL}${item.url}`} height={140} />
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
