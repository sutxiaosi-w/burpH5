<script setup lang="ts">
import { json } from '@codemirror/lang-json'
import { StreamLanguage } from '@codemirror/language'
import { http } from '@codemirror/legacy-modes/mode/http'
import { EditorState, type Extension } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { basicSetup } from 'codemirror'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    mode?: 'http' | 'json' | 'plain'
    readOnly?: boolean
  }>(),
  {
    mode: 'plain',
    readOnly: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const hostElement = ref<HTMLDivElement | null>(null)
let editorView: EditorView | null = null

const languageExtensions = computed<Extension[]>(() => {
  if (props.mode === 'json') {
    return [json()]
  }
  if (props.mode === 'http') {
    return [StreamLanguage.define(http)]
  }
  return []
})

function mountEditor() {
  if (!hostElement.value) return
  editorView = new EditorView({
    parent: hostElement.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        basicSetup,
        ...languageExtensions.value,
        EditorView.lineWrapping,
        EditorView.theme({
          '&': {
            fontSize: '15px',
          },
          '.cm-content': {
            fontFamily: '"JetBrains Mono", "Cascadia Mono", "Sarasa Mono SC", "Consolas", monospace',
            lineHeight: '1.8',
            padding: '14px 0',
          },
          '.cm-gutters': {
            backgroundColor: '#f2faf4',
            color: '#84a392',
            borderRight: '1px solid #d6e7da',
          },
          '.cm-activeLine, .cm-activeLineGutter': {
            backgroundColor: '#eef8f0',
          },
          '.cm-cursor': {
            borderLeftColor: '#4e7d61',
          },
          '.cm-selectionBackground': {
            backgroundColor: '#d7efdf',
          },
        }),
        EditorState.readOnly.of(props.readOnly),
        EditorView.editable.of(!props.readOnly),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            emit('update:modelValue', update.state.doc.toString())
          }
        }),
      ],
    }),
  })
}

watch(
  () => props.modelValue,
  (value) => {
    if (!editorView) return
    const current = editorView.state.doc.toString()
    if (current === value) return
    editorView.dispatch({
      changes: { from: 0, to: current.length, insert: value },
    })
  },
)

watch(
  () => [props.mode, props.readOnly] as const,
  () => {
    if (!hostElement.value) return
    editorView?.destroy()
    editorView = null
    hostElement.value.innerHTML = ''
    mountEditor()
  },
)

onMounted(mountEditor)

onBeforeUnmount(() => {
  editorView?.destroy()
  editorView = null
})
</script>

<template>
  <div ref="hostElement" class="code-editor"></div>
</template>
