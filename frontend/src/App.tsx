import { Trans } from "react-i18next";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import SearchFields from "./components/SearchFields";
import Requests from "./components/RequestList";
import Footer from "./components/Footer";
import FAQ from "./components/FAQ";
import DownloadCounter from "./components/DownloadCounter";
import ThemeSwitcher from "./components/ThemeSwitcher";
import LanguageSwitcher from "./components/LanguageSwitcher";
import AdminPage from "./components/AdminPage";
import { NotificationProvider } from "./components/Notification";
import { DownloadsProvider } from "./DownloadsContext";
import "./App.css";

function HomePage() {
  return (
    <div className="container">
      <div className="page-toolbar">
        <LanguageSwitcher />
        <ThemeSwitcher />
      </div>
      <h1>
        <Trans i18nKey="App.appName">Spotify Downloader</Trans>
      </h1>
      <SearchFields />
      <Requests />
      <DownloadCounter />
      <FAQ />
      <Footer />
    </div>
  );
}

function App() {
  return (
    <NotificationProvider>
      <DownloadsProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </BrowserRouter>
      </DownloadsProvider>
    </NotificationProvider>
  );
}

export default App;
