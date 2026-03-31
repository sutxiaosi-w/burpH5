import { createRouter, createWebHistory } from 'vue-router'

import CollectionsView from '../views/CollectionsView.vue'
import HistoryView from '../views/HistoryView.vue'
import RepeaterView from '../views/RepeaterView.vue'
import SettingsView from '../views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'history', component: HistoryView },
    { path: '/repeater', name: 'repeater', component: RepeaterView },
    { path: '/collections', name: 'collections', component: CollectionsView },
    { path: '/settings', name: 'settings', component: SettingsView },
  ],
})

export default router
