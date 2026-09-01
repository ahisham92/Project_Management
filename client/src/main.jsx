import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import './index.css';

import { AuthProvider, useAuth } from './auth.jsx';
import Layout from './components/Layout.jsx';
import { Spinner } from './components/ui.jsx';

import Login from './pages/Login.jsx';
import Portfolio from './pages/Portfolio.jsx';
import NewProject from './pages/NewProject.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Tasks from './pages/Tasks.jsx';
import Schedule from './pages/Schedule.jsx';
import Budget from './pages/Budget.jsx';
import Timesheet from './pages/Timesheet.jsx';
import Setup from './pages/Setup.jsx';

// Apply the stored theme before first paint so the page never flashes.
const stored = localStorage.getItem('pm-theme');
if (stored && stored !== 'system') document.documentElement.setAttribute('data-theme', stored);

function Gate() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner label="Starting…" />;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Portfolio />} />
        <Route path="/projects/new" element={<NewProject />} />
        <Route path="/projects/:id" element={<Dashboard />} />
        <Route path="/projects/:id/tasks" element={<Tasks />} />
        <Route path="/projects/:id/schedule" element={<Schedule />} />
        <Route path="/projects/:id/budget" element={<Budget />} />
        <Route path="/projects/:id/time" element={<Timesheet />} />
        <Route path="/projects/:id/settings" element={<Setup />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
