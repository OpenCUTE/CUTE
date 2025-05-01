# CUTE

---

[CUTE: A scalable CPU-centric and Ultra-utilized Tensor Engine for convolutions](https://www.sciencedirect.com/science/article/pii/S1383762124000432)

now is CUTEv2

修改chipyard的build.sbt，支持cute作为子模块编译～

```
lazy val cute = (project in file("generators/cute"))
  .dependsOn(boom)
  .settings(libraryDependencies ++= rocketLibDeps.value)
  .settings(commonSettings)
```
