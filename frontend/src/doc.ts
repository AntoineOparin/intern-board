import { mount } from "svelte";
import "./styles/style.css";
import "./styles/features/doc-page.css";
import DocPage from "./pages/doc/DocPage.svelte";

mount(DocPage, { target: document.getElementById("app")! });
