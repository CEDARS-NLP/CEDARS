import { Outlet } from "react-router-dom";
import AppSidebar from "./AppSidebar";

export default function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:px-4 focus:py-2 focus:bg-background focus:text-foreground focus:rounded-md focus:m-2 focus:shadow-md"
      >
        Skip to main content
      </a>
      <AppSidebar />
      <main id="main-content" className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
