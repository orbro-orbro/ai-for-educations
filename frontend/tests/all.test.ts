// The Windows app sandbox can evict Vitest's transformed App module when three
// files import it concurrently. One deterministic entry keeps the real suites
// intact while running them in a single module graph.
import "../src/App.test";
import "../src/DemoNotice.test";
import "./student-flow.test";
import "./teacher-privacy.test";
import "./wave3-integration.test";
