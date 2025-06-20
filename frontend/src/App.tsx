import { Trans, useTranslation } from "react-i18next";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import SearchFields from "./components/SearchFields";
import Requests from "./components/Requests";
import Footer from "./components/Footer";
import FAQ from "./components/FAQ";
import DownloadCounter from "./components/DownloadCounter";
import ThemeSwitcher from "./components/ThemeSwitcher";
import LanguageSwitcher from "./components/LanguageSwitcher";
import AdminPage from "./components/AdminPage";
import "./App.css";

function App() {
  const { t } = useTranslation();

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <h1><Trans i18nKey="App.appName">Spotify Downloader</Trans></h1>
              <SearchFields />
              <Requests />
              <DownloadCounter />
              <FAQ />
              <Footer />
              <ThemeSwitcher />
              <LanguageSwitcher />
            </>
          }
        />
        <Route path="/admin" element={<AdminPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
