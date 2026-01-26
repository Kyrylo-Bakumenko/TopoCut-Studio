import { useState, useEffect, useRef } from 'react';
import {
  Layout,
  Form,
  Input,
  InputNumber,
  Button,
  Card,
  Typography,
  Space,
  Alert,
  Select,
  Switch,
  Tabs,
  Empty,
  Progress,
  Collapse,
  Tag,
  Badge,
  Popover,
  ConfigProvider,
  theme,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  SyncOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import axios from 'axios';
import MapSelector from './components/MapSelector';
import JobResultsPanel from './components/JobResultsPanel';
import type { PipelineConfig, JobInfo } from './types';

const { Header, Content, Sider } = Layout;
const { Title, Text } = Typography;
const { Option } = Select;

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

const DEFAULT_CONFIG: PipelineConfig = {
  experiment: { name: 'web_run_01', output_dir: 'results' },
  region: { center_lat: 44.02383819213837, center_lon: -71.83153152465822, radius_m: 2000 },
  model: {
    width_inches: 5.0,
    height_inches: 5.0,
    layer_thickness_mm: 3.175,
    contour_interval_m: 50.0,
  },
  data: { dem_source: 'glo_30', imagery_source: 'naip', imagery_resolution: '5m' },
  processing: {
    smoothing_sigma: 1.0,
    simplification_tol: 0.5,
    kerf_width_mm: 0.15,
    geometric_smoothing: true,
    nesting: {
      enabled: true,
      sheet_width_in: 24.0,
      sheet_height_in: 12.0,
      sheet_margin_in: 0.125,
      sheet_gap_in: 0.0625,
    },
  },
  export: { format: 'dxf', layers_per_file: 1 },
};

function formatTime(isoString: string): string {
  if (!isoString) return '';
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'failed':
      return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    case 'running':
      return <SyncOutlined spin style={{ color: '#1890ff' }} />;
    case 'pending':
      return <ClockCircleOutlined style={{ color: '#faad14' }} />;
    default:
      return null;
  }
}

function getStatusTag(status: string) {
  switch (status) {
    case 'completed':
      return <Tag color="success">Completed</Tag>;
    case 'failed':
      return <Tag color="error">Failed</Tag>;
    case 'running':
      return <Tag color="processing">Running</Tag>;
    case 'pending':
      return <Tag color="warning">Pending</Tag>;
    default:
      return <Tag>{status}</Tag>;
  }
}

function App() {
  const [form] = Form.useForm<PipelineConfig>();
  const [jobHistory, setJobHistory] = useState<string[]>([]);
  const [expandedJobs, setExpandedJobs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState('map');
  const [isDarkMode, setIsDarkMode] = useState(true);
  // tracks which input should drive derived updates
  const lastEditedRef = useRef<'radius' | 'contour'>('radius');
  // guards against feedback loops during form sync
  const isInternalUpdate = useRef(false);

  // watch relevant form values for map
  const lat = Form.useWatch(['region', 'center_lat'], form) ?? DEFAULT_CONFIG.region.center_lat;
  const lon = Form.useWatch(['region', 'center_lon'], form) ?? DEFAULT_CONFIG.region.center_lon;
  const radius = Form.useWatch(['region', 'radius_m'], form) ?? DEFAULT_CONFIG.region.radius_m;
  const widthIn =
    Form.useWatch(['model', 'width_inches'], form) ?? DEFAULT_CONFIG.model.width_inches;
  const heightIn =
    Form.useWatch(['model', 'height_inches'], form) ?? DEFAULT_CONFIG.model.height_inches;
  const thicknessMm =
    Form.useWatch(['model', 'layer_thickness_mm'], form) ?? DEFAULT_CONFIG.model.layer_thickness_mm;
  const contourInterval =
    Form.useWatch(['model', 'contour_interval_m'], form) ?? DEFAULT_CONFIG.model.contour_interval_m;

  useEffect(() => {
    let isActive = true;
    const ping = async () => {
      try {
        await fetch(`${API_URL}/`, { cache: 'no-store' });
      } catch (err) {
        // ignore failures; this is a best-effort wake-up call
      }
    };
    const startHeartbeat = () => {
      if (!isActive) return;
      ping();
    };

    startHeartbeat();
    const intervalId = window.setInterval(startHeartbeat, 9 * 60 * 1000);

    return () => {
      isActive = false;
      window.clearInterval(intervalId);
    };
  }, []);

  // mutation: submit job
  const submitJob = useMutation({
    mutationFn: async (values: PipelineConfig) => {
      const res = await axios.post(`${API_URL}/jobs`, values);
      return res.data as JobInfo;
    },
    onSuccess: (data) => {
      setJobHistory((prev) => [data.id, ...prev]);
      setExpandedJobs((prev) => (prev.includes(data.id) ? prev : [data.id, ...prev]));
      setActiveTab('jobs');
    },
  });

  // query: get all jobs status (for polling running jobs)
  const { data: allJobs } = useQuery({
    queryKey: ['allJobs', jobHistory],
    queryFn: async () => {
      const res = await axios.get(`${API_URL}/jobs`);
      return res.data as Record<string, JobInfo>;
    },
    refetchInterval: (query) => {
      const jobs = query.state.data as Record<string, JobInfo> | undefined;
      if (!jobs || jobHistory.length === 0) return 2000;
      const hasRunning = jobHistory.some((id) => {
        const job = jobs[id];
        return job && (job.status === 'running' || job.status === 'pending');
      });
      return hasRunning ? 2000 : false;
    },
  });

  // auto-expand and switch to jobs tab when a job completes
  useEffect(() => {
    if (allJobs && jobHistory.length > 0) {
      const latestJob = allJobs[jobHistory[0]];
      if (latestJob?.status === 'completed') {
        setExpandedJobs((prev) => (prev.includes(latestJob.id) ? prev : [latestJob.id, ...prev]));
        setActiveTab('jobs');
      }
    }
  }, [allJobs, jobHistory]);

  const handleMapCoords = (newLat: number, newLon: number) => {
    lastEditedRef.current = 'radius';
    form.setFieldsValue({
      region: {
        center_lat: newLat,
        center_lon: newLon,
      },
    });
  };

  useEffect(() => {
    if (isInternalUpdate.current) return;
    if (!widthIn || !radius || !thicknessMm) return;

    // derive scale to keep physical layer thickness consistent with contour interval
    const widthMm = widthIn * 25.4;
    const scaleMmPerM = widthMm / (2 * radius);

    if (lastEditedRef.current === 'radius') {
      const newContour = thicknessMm / scaleMmPerM;
      if (Number.isFinite(newContour) && Math.abs(newContour - contourInterval) > 0.01) {
        isInternalUpdate.current = true;
        form.setFieldsValue({ model: { contour_interval_m: Number(newContour.toFixed(2)) } });
        setTimeout(() => {
          isInternalUpdate.current = false;
        }, 0);
      }
    } else {
      const newRadius = (contourInterval * widthMm) / (2 * thicknessMm);
      if (Number.isFinite(newRadius) && Math.abs(newRadius - radius) > 0.5) {
        isInternalUpdate.current = true;
        form.setFieldsValue({ region: { radius_m: Number(newRadius.toFixed(1)) } });
        setTimeout(() => {
          isInternalUpdate.current = false;
        }, 0);
      }
    }

    // enforce square model to keep X/Y scaling consistent
    if (widthIn !== heightIn) {
      isInternalUpdate.current = true;
      form.setFieldsValue({ model: { height_inches: widthIn } });
      setTimeout(() => {
        isInternalUpdate.current = false;
      }, 0);
    }
  }, [widthIn, heightIn, radius, thicknessMm, contourInterval, form]);

  const handleFinish = (values: PipelineConfig) => {
    // deep merge logic fixes: processing is an object, so { ...processing } is a shallow merge.
    // if values.processing doesn't contain smoothing_sigma (which isn't in the form), it will be lost if we just overwrite.
    // we must merge nested objects carefully.

    // 1. merge processing
    const mergedProcessing = {
      ...DEFAULT_CONFIG.processing,
      ...values.processing,
      nesting: {
        ...DEFAULT_CONFIG.processing.nesting,
        ...(values.processing?.nesting || {}),
      },
    };

    const payload: PipelineConfig = {
      experiment: { ...DEFAULT_CONFIG.experiment, ...values.experiment },
      region: { ...DEFAULT_CONFIG.region, ...values.region },
      model: { ...DEFAULT_CONFIG.model, ...values.model },
      data: { ...DEFAULT_CONFIG.data, ...values.data },
      processing: mergedProcessing,
      export: { ...DEFAULT_CONFIG.export, ...values.export },
    };
    submitJob.mutate(payload);
  };

  const currentRunningJob = jobHistory.length > 0 ? allJobs?.[jobHistory[0]] : null;
  const isRunning =
    submitJob.isPending ||
    (currentRunningJob &&
      (currentRunningJob.status === 'running' || currentRunningJob.status === 'pending'));

  const handleCollapseChange = (keys: string | string[]) => {
    const keyArray = Array.isArray(keys) ? keys : [keys];
    setExpandedJobs(keyArray);
  };

  const lightTokens = {
    colorPrimary: '#3B82F6',
    colorBgBase: '#F8FAFC',
    colorBgContainer: '#FFFFFF',
    colorText: '#0F172A',
    colorTextSecondary: '#475569',
    colorBorder: '#E2E8F0',
    colorFillSecondary: '#F1F5F9',
    colorLink: '#2563EB',
  };

  const darkTokens = {
    colorPrimary: '#60A5FA',
    colorBgBase: '#0B1220',
    colorBgContainer: '#111827',
    colorText: '#E2E8F0',
    colorTextSecondary: '#94A3B8',
    colorBorder: '#1F2937',
    colorFillSecondary: '#0F172A',
    colorLink: '#93C5FD',
  };

  const headerBg = isDarkMode ? '#0F172A' : '#1E3A8A';
  const headerText = '#FFFFFF';
  const siderBorder = isDarkMode ? '#1F2937' : '#E2E8F0';
  const settingsContent = (
    <div style={{ minWidth: 200 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text>Dark Mode</Text>
        <Switch
          checked={isDarkMode}
          onChange={setIsDarkMode}
          checkedChildren="On"
          unCheckedChildren="Off"
        />
      </div>
    </div>
  );

  return (
    <ConfigProvider
      theme={{
        algorithm: isDarkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: isDarkMode ? darkTokens : lightTokens,
      }}
    >
      <Layout
        style={{
          height: '100vh',
          background: isDarkMode ? darkTokens.colorBgBase : lightTokens.colorBgBase,
        }}
      >
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: headerBg,
          }}
        >
          <Title level={3} style={{ color: headerText, margin: 0 }}>
            Elevation Relief Generator
          </Title>
        </Header>
        <Layout>
          <Sider
            width={400}
            theme={isDarkMode ? 'dark' : 'light'}
            style={{ overflowY: 'auto', padding: '20px', borderRight: `1px solid ${siderBorder}` }}
          >
            <Form
              form={form}
              layout="vertical"
              initialValues={DEFAULT_CONFIG}
              onFinish={handleFinish}
              onValuesChange={(changedValues) => {
                if (isInternalUpdate.current) return;
                // update last edited field to resolve radius/contour coupling
                if (changedValues?.region?.radius_m !== undefined) {
                  lastEditedRef.current = 'radius';
                }
                if (changedValues?.model?.contour_interval_m !== undefined) {
                  lastEditedRef.current = 'contour';
                }
                if (changedValues?.model?.width_inches !== undefined) {
                  lastEditedRef.current = 'radius';
                }
                if (changedValues?.model?.layer_thickness_mm !== undefined) {
                  lastEditedRef.current = 'radius';
                }
              }}
              disabled={!!isRunning}
            >
              <Card title="Region" size="small" style={{ marginBottom: 16 }}>
                <Space>
                  <Form.Item
                    name={['region', 'center_lat']}
                    label="Latitude"
                    rules={[{ required: true }]}
                  >
                    <InputNumber step={0.0001} style={{ width: 110 }} />
                  </Form.Item>
                  <Form.Item
                    name={['region', 'center_lon']}
                    label="Longitude"
                    rules={[{ required: true }]}
                  >
                    <InputNumber step={0.0001} style={{ width: 110 }} />
                  </Form.Item>
                </Space>
                <Form.Item name={['region', 'radius_m']} label="Radius (m)">
                  <InputNumber step={100} style={{ width: '100%' }} />
                </Form.Item>
              </Card>

              <Card title="Physical Model" size="small" style={{ marginBottom: 16 }}>
                <Space>
                  <Form.Item name={['model', 'width_inches']} label="Width (in)">
                    <InputNumber step={0.1} />
                  </Form.Item>
                  <Form.Item name={['model', 'height_inches']} label="Height (in)">
                    <InputNumber step={0.1} disabled />
                  </Form.Item>
                </Space>
                <Form.Item name={['model', 'layer_thickness_mm']} label="Layer Thickness">
                  <Select>
                    <Option value={3.175}>1/8" (3.175 mm)</Option>
                    <Option value={1.5875}>1/16" (1.5875 mm)</Option>
                  </Select>
                </Form.Item>
                <Form.Item name={['model', 'contour_interval_m']} label="Contour Interval (m)">
                  <InputNumber step={1} />
                </Form.Item>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  Width sets the model scale. Radius and contour interval auto-adjust to match the
                  selected layer thickness.
                </Typography.Paragraph>
              </Card>

              <Card title="Data Sources" size="small" style={{ marginBottom: 16 }}>
                <Form.Item name={['data', 'dem_source']} label="DEM Source">
                  <Select>
                    <Option value="glo_30">Copernicus GLO-30 (Global)</Option>
                    <Option value="3dep">USGS 3DEP (USA Only)</Option>
                  </Select>
                </Form.Item>
                <Form.Item name={['data', 'imagery_source']} label="Imagery Source">
                  <Select>
                    <Option value="naip">NAIP (USA Only)</Option>
                    <Option value="sentinel-2-l2a">Sentinel-2 (Global)</Option>
                  </Select>
                </Form.Item>
                <Form.Item name={['data', 'imagery_resolution']} label="Imagery Resolution">
                  <Select>
                    <Option value="1m">1m (Native - Slow)</Option>
                    <Option value="5m">5m (Preview)</Option>
                    <Option value="10m">10m (Fast)</Option>
                  </Select>
                </Form.Item>
              </Card>

              <Card
                title={
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span>Processing</span>
                    <Form.Item
                      name={['processing', 'geometric_smoothing']}
                      valuePropName="checked"
                      style={{ marginBottom: 0 }}
                    >
                      <Switch checkedChildren="Smooth" unCheckedChildren="Chunky" />
                    </Form.Item>
                  </div>
                }
                size="small"
                style={{ marginBottom: 16 }}
              >
                <Typography.Text strong>Smooth Borders</Typography.Text>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  Applies geometric smoothing to reduce jagged contour edges for cleaner laser
                  paths.
                </Typography.Paragraph>
              </Card>

              <Card
                title={
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span>Nesting</span>
                    <Form.Item
                      name={['processing', 'nesting', 'enabled']}
                      valuePropName="checked"
                      style={{ marginBottom: 0 }}
                    >
                      <Switch />
                    </Form.Item>
                  </div>
                }
                size="small"
                style={{ marginBottom: 16 }}
              >
                <Typography.Text strong>Enable Nesting</Typography.Text>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
                  Packs layers onto sheet layouts for efficient cutting and composite previews.
                </Typography.Paragraph>
                <Space>
                  <Form.Item
                    name={['processing', 'nesting', 'sheet_width_in']}
                    label="Sheet Width (in)"
                  >
                    <InputNumber step={1} />
                  </Form.Item>
                  <Form.Item
                    name={['processing', 'nesting', 'sheet_height_in']}
                    label="Sheet Height (in)"
                  >
                    <InputNumber step={1} />
                  </Form.Item>
                </Space>
                <Form.Item
                  name={['processing', 'nesting', 'sheet_margin_in']}
                  label="Sheet Margin (in)"
                >
                  <InputNumber step={0.0625} />
                </Form.Item>
                <Form.Item name={['processing', 'nesting', 'sheet_gap_in']} label="Part Gap (in)">
                  <InputNumber step={0.03125} />
                </Form.Item>
              </Card>

              <Card title="Experiment" size="small" style={{ marginBottom: 16 }}>
                <Form.Item name={['experiment', 'name']} label="Name" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
              </Card>

              <Button
                type="primary"
                htmlType="submit"
                loading={!!isRunning}
                block
                size="large"
                style={{ marginBottom: 16 }}
              >
                {isRunning ? 'Processing...' : 'Generate Relief'}
              </Button>

              {isRunning && currentRunningJob && (
                <div style={{ marginTop: 16 }}>
                  <Progress percent={currentRunningJob.progress} status="active" />
                  <Typography.Text type="secondary">{currentRunningJob.message}</Typography.Text>
                </div>
              )}

              {submitJob.isError && (
                <Alert
                  type="error"
                  title="Submission Failed"
                  description={submitJob.error.message}
                  style={{ marginTop: 16 }}
                />
              )}
            </Form>
          </Sider>
          <Content
            style={{
              position: 'relative',
              background: isDarkMode ? darkTokens.colorBgContainer : lightTokens.colorBgContainer,
            }}
          >
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              type="card"
              style={{ height: '100%', padding: '10px 10px 0 10px' }}
              tabBarExtraContent={{
                right: (
                  <Popover content={settingsContent} title="Settings" trigger="click">
                    <Button
                      aria-label="Settings"
                      icon={<SettingOutlined />}
                      type="text"
                      size="small"
                    />
                  </Popover>
                ),
              }}
              items={[
                {
                  key: 'map',
                  label: 'Map Selector',
                  children: (
                    <div
                      style={{
                        position: 'relative',
                        width: '100%',
                        height: 'calc(100vh - 64px - 60px)',
                      }}
                    >
                      <div style={{ position: 'absolute', inset: 0 }}>
                        <MapSelector
                          lat={lat}
                          lon={lon}
                          radius={radius}
                          setCoords={handleMapCoords}
                        />
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'jobs',
                  label: (
                    <Badge count={jobHistory.length} size="small" offset={[8, 0]}>
                      <span>Job History</span>
                    </Badge>
                  ),
                  children: (
                    <div style={{ padding: 16, height: 'calc(100vh - 130px)', overflowY: 'auto' }}>
                      {jobHistory.length === 0 ? (
                        <Empty description="No jobs run yet. Configure settings and click Generate Relief." />
                      ) : (
                        <Collapse
                          activeKey={expandedJobs}
                          onChange={handleCollapseChange}
                          items={jobHistory
                            .map((jId, idx) => {
                              const job = allJobs?.[jId];
                              if (!job) return null;

                              return {
                                key: jId,
                                label: (
                                  <div
                                    style={{
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 12,
                                      width: '100%',
                                    }}
                                  >
                                    {getStatusIcon(job.status)}
                                    <span style={{ fontWeight: 500 }}>
                                      Run #{jobHistory.length - idx}
                                    </span>
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      {formatTime(job.created_at)}
                                    </Text>
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      • {job.config_summary}
                                    </Text>
                                    <div style={{ marginLeft: 'auto' }}>
                                      {getStatusTag(job.status)}
                                    </div>
                                  </div>
                                ),
                                children: (
                                  <div>
                                    {job.status === 'running' || job.status === 'pending' ? (
                                      <div style={{ padding: 20 }}>
                                        <Progress percent={job.progress} status="active" />
                                        <Typography.Text type="secondary">
                                          {job.message}
                                        </Typography.Text>
                                      </div>
                                    ) : job.status === 'failed' ? (
                                      <Alert
                                        type="error"
                                        title="Job Failed"
                                        description={job.error}
                                      />
                                    ) : job.status === 'completed' ? (
                                      <JobResultsPanel jobId={jId} isCompleted={true} />
                                    ) : null}
                                  </div>
                                ),
                              };
                            })
                            .filter((item): item is NonNullable<typeof item> => item !== null)}
                        />
                      )}
                    </div>
                  ),
                },
              ]}
            />
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
