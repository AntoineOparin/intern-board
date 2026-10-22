// The tracker side panel, opened from a board row's stage button or a kanban card.
export const drawer = $state({ id: null as string | null });
export const openDrawer = (id: string) => { drawer.id = id; };
export const closeDrawer = () => { drawer.id = null; };
