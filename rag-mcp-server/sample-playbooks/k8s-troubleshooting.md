---
title: Kubernetes Pod Troubleshooting Guide
category: kubernetes
severity: high
---

# Kubernetes Pod Troubleshooting Guide

This playbook covers common Kubernetes pod issues and their resolutions.

## CrashLoopBackOff

When a pod is stuck in CrashLoopBackOff, the container is crashing repeatedly.

### Diagnosis Steps

1. Check pod status:
   ```bash
   kubectl get pod <pod-name> -o wide
   ```

2. Check pod events:
   ```bash
   kubectl describe pod <pod-name>
   ```

3. Check container logs:
   ```bash
   kubectl logs <pod-name> --previous
   ```

### Common Causes

- **Application Error**: Check logs for stack traces
- **Missing ConfigMap/Secret**: Verify all mounted configs exist
- **Resource Limits**: Container may be OOMKilled
- **Liveness Probe Failure**: Adjust probe thresholds

### Resolution

1. If OOMKilled, increase memory limits in deployment
2. If config missing, create the required ConfigMap/Secret
3. If probe failing, adjust `initialDelaySeconds` or thresholds

## OOMKilled

The container was terminated due to exceeding memory limits.

### Diagnosis Steps

1. Check pod events for OOMKilled:
   ```bash
   kubectl describe pod <pod-name> | grep -A5 "Last State"
   ```

2. Check current memory usage:
   ```bash
   kubectl top pod <pod-name>
   ```

3. Review memory limits in deployment:
   ```bash
   kubectl get deployment <deployment-name> -o yaml | grep -A10 resources
   ```

### Resolution

1. Increase memory limits in the deployment spec
2. Investigate memory leaks in the application
3. Consider horizontal scaling instead of vertical

## ImagePullBackOff

The container image cannot be pulled from the registry.

### Diagnosis Steps

1. Check pod events:
   ```bash
   kubectl describe pod <pod-name> | grep -A5 "Events"
   ```

2. Verify image exists:
   ```bash
   aws ecr describe-images --repository-name <repo> --image-ids imageTag=<tag>
   ```

3. Check pull secrets:
   ```bash
   kubectl get pod <pod-name> -o yaml | grep imagePullSecrets
   ```

### Resolution

1. Verify the image tag exists in the registry
2. Check registry authentication (imagePullSecrets)
3. Ensure the node can reach the registry network
