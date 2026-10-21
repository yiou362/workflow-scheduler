import { Layout, Menu, Space, Tag, Typography } from 'antd'
import {
  ApiOutlined,
  DashboardOutlined,
  HistoryOutlined,
  ScheduleOutlined,
} from '@ant-design/icons'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { useMeta } from './hooks/useMeta'
import DashboardPage from './pages/DashboardPage'
import EndpointsPage from './pages/EndpointsPage'
import EndpointDetailPage from './pages/EndpointDetailPage'
import EndpointFormPage from './pages/EndpointFormPage'
import TasksPage from './pages/TasksPage'
import TaskDetailPage from './pages/TaskDetailPage'
import TaskFormPage from './pages/TaskFormPage'
import RunsPage from './pages/RunsPage'
import RunDetailPage from './pages/RunDetailPage'
import NotFoundPage from './pages/NotFoundPage'

const { Header, Sider, Content } = Layout

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: <Link to="/">Dashboard</Link> },
  { key: '/endpoints', icon: <ApiOutlined />, label: <Link to="/endpoints">Endpoints</Link> },
  { key: '/tasks', icon: <ScheduleOutlined />, label: <Link to="/tasks">Tasks</Link> },
  { key: '/runs', icon: <HistoryOutlined />, label: <Link to="/runs">Runs</Link> },
]

function selectedKey(pathname: string): string {
  if (pathname.startsWith('/endpoints')) return '/endpoints'
  if (pathname.startsWith('/tasks')) return '/tasks'
  if (pathname.startsWith('/runs')) return '/runs'
  return '/'
}

export default function App() {
  const location = useLocation()
  const meta = useMeta()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={208} breakpoint="lg" collapsedWidth={64}>
        <div className="brand">PromptOps</div>
        <Menu theme="dark" mode="inline" selectedKeys={[selectedKey(location.pathname)]} items={menuItems} />
      </Sider>
      <Layout>
        <Header className="header">
          <Space size="middle">
            <Typography.Text strong>OpenCode task scheduling and execution tracing</Typography.Text>
            {meta.data ? <Tag>UTC{meta.data.utc_offset}</Tag> : null}
          </Space>
          <Typography.Text type="secondary">
            {meta.data ? `v${meta.data.version}` : ''} · single-node internal tool
          </Typography.Text>
        </Header>
        <Content className="content">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/endpoints" element={<EndpointsPage />} />
            <Route path="/endpoints/new" element={<EndpointFormPage />} />
            <Route path="/endpoints/:id" element={<EndpointDetailPage />} />
            <Route path="/endpoints/:id/edit" element={<EndpointFormPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/tasks/new" element={<TaskFormPage />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            <Route path="/tasks/:id/edit" element={<TaskFormPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/:id" element={<RunDetailPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
