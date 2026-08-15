import { Outlet } from 'react-router-dom';

export default function RootLayout() {
  return (
    <div className="h-full bg-bg text-text">
      <Outlet />
    </div>
  );
}
