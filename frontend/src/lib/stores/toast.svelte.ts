// One toast at a time, hidden after 5 seconds (like the old #toast).
export const toastState = $state({ message: "", visible: false });
let timer: ReturnType<typeof setTimeout> | undefined;

export function toast(message: string) {
  toastState.message = message;
  toastState.visible = true;
  clearTimeout(timer);
  timer = setTimeout(() => { toastState.visible = false; }, 5000);
}
