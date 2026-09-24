import Shell from "./components/Shell";
import { href, useRoute } from "./lib/router";
import CreditsPage from "./pages/CreditsPage";
import DiscoverPage from "./pages/DiscoverPage";
import HomePage from "./pages/HomePage";
import OnboardingPage from "./pages/OnboardingPage";
import PlacePage from "./pages/PlacePage";
import PlanPage from "./pages/PlanPage";
import { PlansPage, SavedPlanPage } from "./pages/PlansPage";
import ProfilePage from "./pages/ProfilePage";
import SignInPage from "./pages/SignInPage";
import "./App.css";

export default function App() {
  const { parts, query } = useRoute();
  const [section = "", id] = parts;

  // Sign-up and sign-in use their own full-screen layout.
  if (section === "welcome") return <OnboardingPage />;
  if (section === "signin") return <SignInPage />;

  let page;
  switch (section) {
    case "":
      page = <HomePage />;
      break;
    case "plan":
      // Keyed by the query string: arriving from Plan with AI with a new
      // request remounts the page instead of showing the previous state.
      page = <PlanPage key={query.get("from") ?? "direct"} />;
      break;
    case "discover":
      page = <DiscoverPage key={query.get("q") ?? ""} initialQuery={query.get("q") ?? ""} />;
      break;
    case "place":
      page = <PlacePage key={id} id={Number(id)} />;
      break;
    case "plans":
      page = id ? <SavedPlanPage key={id} id={id} /> : <PlansPage />;
      break;
    case "profile":
      page = <ProfilePage />;
      break;
    case "credits":
      page = <CreditsPage />;
      break;
    default:
      page = (
        <div className="page-narrow empty-state">
          <h3>Page not found</h3>
          <p><a href={href("/")}>Go home</a></p>
        </div>
      );
  }

  return <Shell active={section}>{page}</Shell>;
}