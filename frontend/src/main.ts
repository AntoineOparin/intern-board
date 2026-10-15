import { mount } from "svelte";
// Design tokens and shared styles (light theme only).
import "./styles/style.css";
import "./styles/features/ranking.css";
import "./styles/features/documents.css";
import "./styles/features/people.css";
import App from "./App.svelte";

mount(App, { target: document.getElementById("app")! });
