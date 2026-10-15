<script lang="ts">
  import { toastState } from "../stores/toast.svelte";
</script>

<div id="toast" class="toast" role="alert" hidden={!toastState.visible}>{toastState.message}</div>
