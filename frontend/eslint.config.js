/**
 * eslint.config.js：ESLint flat config
 * 作用：typescript-eslint recommended + eslint-plugin-vue(vue3-recommended) + 关闭与 Prettier 冲突的格式规则
 */
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import prettier from 'eslint-config-prettier'

export default tseslint.config(
  // 忽略构建产物与静态资源
  {
    ignores: ['dist/**', 'node_modules/**', 'public/**', 'coverage/**']
  },
  // TypeScript 推荐规则（含 eslint-recommended 中被 TS 替代的核心规则关闭）
  ...tseslint.configs.recommended,
  // Vue 3 官方推荐规则（essential 为 error，strongly-recommended/recommended 为 warn）
  ...pluginVue.configs['flat/recommended'],
  // .vue 内 <script lang="ts"> 交给 TypeScript 解析器处理
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser
      }
    }
  },
  // 项目惯例：对齐存量代码风格的规则调整
  {
    rules: {
      // 项目存在 App/Home/Pay 等单词组件名，豁免该命名限制
      'vue/multi-word-component-names': 'off',
      // 存量代码广泛使用 any，降级为 warning 作提示，不阻塞 lint
      '@typescript-eslint/no-explicit-any': 'warn'
    }
  },
  // 必须放最后：关闭所有与 Prettier 冲突的格式类规则
  prettier
)
