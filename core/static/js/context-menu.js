function openFolderContextMenu(event, entry) {
  event.preventDefault();
  state.contextFolder = entry;
  updatePluginContextMenuVisibility("folder");
  if (!Array.from(folderContextMenu.children).some((item) => !item.hidden)) {
    return;
  }
  folderContextMenu.hidden = false;
  const menuRect = folderContextMenu.getBoundingClientRect();
  const left = Math.min(event.clientX, window.innerWidth - menuRect.width - 8);
  const top = Math.min(event.clientY, window.innerHeight - menuRect.height - 8);
  folderContextMenu.style.left = `${Math.max(8, left)}px`;
  folderContextMenu.style.top = `${Math.max(8, top)}px`;
}

function closeFolderContextMenu() {
  folderContextMenu.hidden = true;
}

function updatePluginContextMenuVisibility(target) {
  folderContextMenu.querySelectorAll("[data-plugin-trigger='1']").forEach((item) => {
    item.hidden = item.dataset.triggerTarget && item.dataset.triggerTarget !== target;
  });
}
