import { mount } from "svelte";
// The old stylesheet is shared during the migration, so both apps use the same tokens (light theme only).
import "../../board/static/style.css";
import "../../board/static/features/people.css";
import App from "./App.svelte";

mount(App, { target: document.getElementById("app")! });
