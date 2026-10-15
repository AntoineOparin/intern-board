import { mount } from "svelte";
import "../../board/static/style.css";
import "../../board/static/features/doc-page.css";
import DocPage from "./pages/doc/DocPage.svelte";

mount(DocPage, { target: document.getElementById("app")! });
